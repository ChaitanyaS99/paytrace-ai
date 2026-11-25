import io
import json
from pathlib import Path

import pandas as pd
import pytest

from paytrace import ingest

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "freelancer"


def as_bytes(df: pd.DataFrame, kind: str) -> bytes:
    if kind == "csv":
        return df.to_csv(index=False).encode()
    if kind == "json":
        return json.dumps(df.to_dict(orient="records")).encode()
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


@pytest.mark.parametrize("table", ["expected", "received", "adjustments"])
def test_sample_files_load_with_no_manual_mapping(table):
    clean, problems, info = ingest.load_file(SAMPLES / f"{table}.csv", table)
    assert problems == []
    assert len(clean) == info["rows_read"] > 0


@pytest.mark.parametrize("kind", ["csv", "json", "xlsx"])
def test_all_formats_read_the_same(kind):
    original = pd.read_csv(SAMPLES / "received.csv", dtype=str)
    df = ingest.read_file(as_bytes(original, kind), f"upload.{kind}")
    assert list(df.columns) == list(original.columns)
    assert len(df) == len(original)


def test_json_wrapped_in_object():
    data = json.dumps({"payments": [{"id": "1", "client": "Acme", "date": "2026-01-05", "net": "100"}]}).encode()
    df = ingest.read_file(data, "x.json")
    assert df.loc[0, "client"] == "Acme"


def test_semicolon_csv_and_bom():
    data = "﻿Date;Client;Net\n2026-01-05;Acme;100\n".encode("utf-8")
    df = ingest.read_file(data, "x.csv")
    assert list(df.columns) == ["Date", "Client", "Net"]


def test_unsupported_type():
    with pytest.raises(ValueError, match="Unsupported"):
        ingest.read_file(b"abc", "notes.pdf")


def test_fuzzy_mapping_on_messy_headers():
    raw = pd.DataFrame({
        "Txn ID": ["T1"], "Client Name": ["Acme"], "Paid On": ["2026-02-01"],
        "Gross Pay": ["$500"], "Service Fee": ["50"], "Net Pay": ["450"], "Notes": ["x"],
    })
    mapping, template = ingest.propose_mapping(raw, "received")
    assert template is None
    assert mapping == {
        "payment_id": "Txn ID", "payer": "Client Name", "payment_date": "Paid On",
        "gross_amount": "Gross Pay", "fee_amount": "Service Fee", "net_amount": "Net Pay", "memo": "Notes",
    }


def test_paypal_template_detected_and_applied():
    raw = pd.DataFrame({
        "Date": ["01/05/2026", "01/09/2026"], "Name": ["Acme", "Acme"], "Type": ["Payment", "Refund"],
        "Gross": ["500.00", "-20.00"], "Fee": ["-14.80", "0.00"], "Net": ["485.20", "-20.00"],
        "Transaction ID": ["9XA", "9XB"],
    })
    mapping, template = ingest.propose_mapping(raw, "received")
    assert template == "paypal"
    table, problems = ingest.to_table(raw, mapping, "received", template)
    assert problems == []
    assert len(table) == 1  # refund row dropped
    assert table.loc[0, "fee_amount"] == pytest.approx(14.80)


def test_doordash_template_fills_payer_and_ids():
    raw = pd.DataFrame({"Date": ["2026-01-05"], "Base Pay": ["80"], "Tips": ["20"], "Total Pay": ["100"]})
    table, problems, info = ingest.load_file(as_bytes(raw, "csv"), "received", "dd.csv")
    assert info["template"] == "doordash"
    assert problems == []
    assert table.loc[0, "payer"] == "DoorDash" and table.loc[0, "payment_id"] == "P00001"


def test_missing_required_column_is_reported_not_raised():
    raw = pd.DataFrame({"Client": ["Acme"], "Net": ["100"]})
    _, problems, _ = ingest.load_file(as_bytes(raw, "csv"), "received", "x.csv")
    assert any("payment_date" in p for p in problems)


def test_questionnaire_monthly():
    exp = ingest.questionnaire_to_expected([{
        "payer": "Acme Co", "rate": 50, "units_per_period": 20, "period": "monthly",
        "terms_days": 30, "start_date": "2026-01-01", "end_date": "2026-04-30",
    }])
    assert len(exp) == 4
    assert exp["expected_amount"].eq(1000.0).all()
    assert exp.loc[0, "work_period_end"] == pd.Timestamp("2026-01-31")
    assert exp.loc[0, "due_date"] == pd.Timestamp("2026-03-02")
    assert exp["expected_id"].is_unique


def test_questionnaire_weekly_multiple_payers():
    exp = ingest.questionnaire_to_expected([
        {"payer": "A", "rate": 20, "units_per_period": 10, "period": "weekly", "terms_days": 0,
         "start_date": "2026-01-05", "end_date": "2026-02-01"},
        {"payer": "B", "rate": 30, "units_per_period": 5, "period": "biweekly", "terms_days": 15,
         "start_date": "2026-01-05", "end_date": "2026-02-01"},
    ])
    assert (exp["payer"] == "A").sum() == 4
    assert (exp["payer"] == "B").sum() == 2


def test_questionnaire_bad_period():
    with pytest.raises(ValueError):
        ingest.questionnaire_to_expected([{"payer": "A", "rate": 1, "units_per_period": 1,
                                           "period": "daily", "start_date": "2026-01-01"}])
