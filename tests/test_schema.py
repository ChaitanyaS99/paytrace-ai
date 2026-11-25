import pandas as pd
import pytest

from paytrace import schema


def expected_df(**overrides):
    base = {
        "expected_id": ["E1", "E2"],
        "payer": ["Acme", "Beta"],
        "expected_amount": ["1,200.00", "$450"],
        "due_date": ["2026-03-01", "03/15/2026"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_valid_expected_has_no_problems():
    df, problems = schema.load(expected_df(), "expected")
    assert problems == []
    assert df["expected_amount"].tolist() == [1200.0, 450.0]
    assert str(df["due_date"].dtype).startswith("datetime64")
    assert "agreed_fee_pct" in df.columns  # optional column added


def test_missing_required_column_reported():
    raw = expected_df().drop(columns=["due_date"])
    _, problems = schema.load(raw, "expected")
    assert problems == ["expected: missing required column(s): due_date"]


def test_bad_values_reported_with_row_numbers():
    raw = expected_df(expected_amount=["abc", "-5"], due_date=["not a date", "2026-01-01"])
    _, problems = schema.load(raw, "expected")
    text = " | ".join(problems)
    assert "expected_amount: missing or non-numeric value in row(s) 2" in text
    assert "expected_amount: negative value in row(s) 3" in text
    assert "due_date: missing or unreadable date in row(s) 2" in text


def test_duplicate_ids_reported():
    _, problems = schema.load(expected_df(expected_id=["E1", "E1"]), "expected")
    assert any("duplicate id" in p for p in problems)


def test_empty_table_reported():
    _, problems = schema.load(pd.DataFrame(columns=schema.EXPECTED.required), "expected")
    assert problems == ["expected: no rows found"]


def test_received_derives_net_and_fee():
    raw = pd.DataFrame({
        "payment_id": ["P1", "P2"],
        "payer": ["Acme", "Acme"],
        "payment_date": ["2026-03-04", "2026-03-20"],
        "gross_amount": [1000, 500],
        "fee_amount": [100, None],
        "net_amount": [None, 450],
    })
    df, problems = schema.load(raw, "received")
    assert problems == []
    assert df["net_amount"].tolist() == [900.0, 450.0]
    assert df["fee_amount"].tolist() == [100.0, 50.0]


def test_received_net_above_gross_flagged():
    raw = pd.DataFrame({
        "payment_id": ["P1"], "payer": ["Acme"], "payment_date": ["2026-03-04"],
        "gross_amount": [100], "net_amount": [120],
    })
    _, problems = schema.load(raw, "received")
    assert any("larger than gross" in p for p in problems)


def test_adjustments_normalise_and_check_types():
    raw = pd.DataFrame({
        "adjustment_id": ["A1", "A2"], "payer": ["Acme", "Acme"],
        "date": ["2026-03-01", "2026-03-02"], "type": ["Fee", "penalty"],
        "amount": [14, 20],
    })
    df, problems = schema.load(raw, "adjustments")
    assert df["type"].tolist()[0] == "fee"
    assert df["disclosed"].tolist() == ["unknown", "unknown"]
    assert len(problems) == 1 and "adjustments.type" in problems[0]


def test_adjustments_missing_type_column_reported():
    raw = pd.DataFrame({"adjustment_id": ["A1"], "payer": ["Acme"], "date": ["2026-03-01"], "amount": [5]})
    _, problems = schema.load(raw, "adjustments")
    assert problems == ["adjustments: missing required column(s): type"]


def test_empty_frames_are_typed():
    for name in schema.SPECS:
        df = schema.empty(name)
        assert list(df.columns) == schema.get_spec(name).all


def test_unknown_table_raises():
    with pytest.raises(ValueError):
        schema.get_spec("payroll")
