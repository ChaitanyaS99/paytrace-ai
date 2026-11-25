"""Load payment records from files or questionnaire answers.

    raw = read_file(upload, "export.csv")
    mapping, template = propose_mapping(raw, "received")
    table, problems = to_table(raw, mapping, "received", template)
"""

from __future__ import annotations

import io
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import IO

import pandas as pd

from paytrace import schema

TEMPLATES: dict = {
    k: v for k, v in json.loads((Path(__file__).with_name("templates.json")).read_text()).items()
    if not k.startswith("_")
}

# Common header names for each column, compared case- and punctuation-insensitively
SYNONYMS: dict[str, list[str]] = {
    "expected_id": ["expected id", "invoice", "invoice id", "invoice number", "invoice no", "bill id"],
    "payment_id": ["payment id", "transaction id", "txn id", "id", "ref id", "payout id"],
    "adjustment_id": ["adjustment id", "adj id", "id"],
    "payer": ["payer", "client", "customer", "company", "name", "from", "platform", "team", "customer name",
              "client name", "payer name", "company name", "business name", "employer"],
    "expected_amount": ["expected amount", "amount due", "invoice amount", "amount", "total", "owed"],
    "due_date": ["due date", "due", "payment due", "due on"],
    "payment_date": ["payment date", "paid on", "date paid", "date", "deposit date", "created", "created date"],
    "net_amount": ["net amount", "net", "net pay", "amount received", "payout", "total pay", "amount"],
    "gross_amount": ["gross amount", "gross", "gross pay", "subtotal"],
    "fee_amount": ["fee", "fees", "fee amount", "service fee", "platform fee", "commission"],
    "reference": ["reference", "ref", "invoice reference", "invoice number", "po"],
    "memo": ["memo", "description", "note", "notes", "details", "type"],
    "date": ["date", "adjustment date", "created"],
    "type": ["type", "adjustment type", "category"],
    "amount": ["amount", "value", "total"],
    "disclosed": ["disclosed", "notified", "explained"],
    "work_period_start": ["period start", "start date", "work start"],
    "work_period_end": ["period end", "end date", "work end"],
    "description": ["description", "item", "service", "project"],
    "rate": ["rate", "hourly rate", "unit rate", "price"],
    "units": ["units", "hours", "quantity", "qty"],
    "agreed_fee_pct": ["agreed fee pct", "fee percent", "fee rate", "commission rate"],
}

MATCH_THRESHOLD = 0.82


def read_file(source: str | Path | bytes | IO, filename: str | None = None) -> pd.DataFrame:
    """Read a CSV, JSON or Excel file from a path, bytes or file object.
    Values are read as text and typed later by schema.coerce."""
    name = (filename or getattr(source, "name", None) or str(source)).lower()
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    elif isinstance(source, bytes):
        data = source
    else:
        data = source.read()

    if name.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(data), dtype=str)
    elif name.endswith(".json"):
        df = _read_json(data)
    elif name.endswith((".csv", ".txt")):
        df = _read_csv(data)
    else:
        raise ValueError("Unsupported file type. Upload a CSV, JSON, or Excel (.xlsx) file.")

    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df.reset_index(drop=True)


def _read_csv(data: bytes) -> pd.DataFrame:
    text = data.decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(text), dtype=str, sep=None, engine="python")


def _read_json(data: bytes) -> pd.DataFrame:
    obj = json.loads(data.decode("utf-8-sig"))
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list)]
        if not lists:
            raise ValueError("JSON file must contain a list of records.")
        obj = lists[0]
    return pd.json_normalize(obj).astype(str).replace({"nan": None, "None": None})


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def detect_template(df: pd.DataFrame, table: str | None = None) -> str | None:
    headers = {_norm(c) for c in df.columns}
    best, best_score = None, 0.0
    for key, t in TEMPLATES.items():
        if table and t["table"] != table:
            continue
        sig = [_norm(s) for s in t["signature"]]
        score = sum(s in headers for s in sig) / len(sig)
        if score == 1.0 and score > best_score:
            best, best_score = key, score
    return best


def propose_mapping(df: pd.DataFrame, table: str) -> tuple[dict[str, str], str | None]:
    """Return ({canonical_column: source_column}, template_key or None)."""
    spec = schema.get_spec(table)
    template = detect_template(df, table)
    if template:
        by_norm = {_norm(c): c for c in df.columns}
        mapping = {canon: by_norm[_norm(src)] for canon, src in TEMPLATES[template]["mapping"].items()
                   if _norm(src) in by_norm}
        return mapping, template
    return _fuzzy_mapping(list(df.columns), spec.all), None


def _fuzzy_mapping(source_cols: list[str], targets: list[str]) -> dict[str, str]:
    scores = []
    for target in targets:
        names = [_norm(target)] + [_norm(s) for s in SYNONYMS.get(target, [])]
        for col in source_cols:
            n = _norm(col)
            if n in names:
                # Exact matches outrank fuzzy ones; earlier synonyms take priority
                score = 2.0 - names.index(n) * 0.01
            else:
                score = max(SequenceMatcher(None, n, s).ratio() for s in names)
            if score >= MATCH_THRESHOLD:
                scores.append((score, target, col))
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for _, target, col in sorted(scores, key=lambda x: -x[0]):
        if target not in mapping and col not in used:
            mapping[target] = col
            used.add(col)
    return mapping


def to_table(df: pd.DataFrame, mapping: dict[str, str], table: str,
             template: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Rename columns per mapping, apply template rules, then coerce and validate."""
    spec = schema.get_spec(table)
    t = TEMPLATES.get(template, {}) if template else {}
    out = pd.DataFrame({canon: df[src].values for canon, src in mapping.items() if src in df.columns})

    if "payer" not in out and t.get("default_payer"):
        out["payer"] = t["default_payer"]
    if spec.id_column not in out:
        prefix = {"expected": "E", "received": "P", "adjustments": "A"}[table]
        out[spec.id_column] = [f"{prefix}{i:05d}" for i in range(1, len(out) + 1)]

    out = schema.coerce(out, table)

    if t.get("fee_is_negative") and "fee_amount" in out:
        out["fee_amount"] = out["fee_amount"].abs()
    if t.get("positive_only"):
        col = t["positive_only"]
        out = out[out[col].isna() | (out[col] > 0)].reset_index(drop=True)
    if table == "received" and "gross_amount" in out:
        out["net_amount"] = out["net_amount"].fillna(out["gross_amount"])

    return out, schema.validate(out, table)


def load_file(source, table: str, filename: str | None = None) -> tuple[pd.DataFrame, list[str], dict]:
    """Read, map and convert a file in one call. Returns (table, problems, info)."""
    raw = read_file(source, filename)
    mapping, template = propose_mapping(raw, table)
    clean, problems = to_table(raw, mapping, table, template)
    return clean, problems, {"mapping": mapping, "template": template, "rows_read": len(raw)}


PERIOD_DAYS = {"weekly": 7, "biweekly": 14, "monthly": None}


def questionnaire_to_expected(answers: list[dict], end_date: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Build expected payments from questionnaire answers (one dict per payer).

    Keys: payer, rate, units_per_period, period (weekly, biweekly or monthly),
    terms_days, start_date, and optionally end_date, agreed_fee_pct, description.
    Each period is invoiced on its last day and due `terms_days` later.
    """
    end_default = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
    rows = []
    for a in answers:
        period = a.get("period", "monthly")
        if period not in PERIOD_DAYS:
            raise ValueError(f"period must be one of {list(PERIOD_DAYS)}")
        start = pd.Timestamp(a["start_date"])
        end = pd.Timestamp(a.get("end_date") or end_default)
        rate, units = float(a["rate"]), float(a["units_per_period"])
        terms = int(a.get("terms_days", 30))
        step = pd.DateOffset(months=1) if period == "monthly" else pd.Timedelta(days=PERIOD_DAYS[period])

        period_start, n = start, 0
        while True:
            invoice = period_start + step - pd.Timedelta(days=1)
            if invoice > end:
                break
            n += 1
            rows.append(dict(
                expected_id=f"Q-{_norm(a['payer']).replace(' ', '-')}-{n:03d}",
                payer=a["payer"],
                expected_amount=round(rate * units, 2),
                due_date=invoice + pd.Timedelta(days=terms),
                work_period_start=period_start,
                work_period_end=invoice,
                description=a.get("description", f"{period} work"),
                rate=rate,
                units=units,
                agreed_fee_pct=a.get("agreed_fee_pct", 0.0),
                source="questionnaire",
            ))
            period_start = period_start + step

    if not rows:
        return schema.empty("expected")
    return schema.coerce(pd.DataFrame(rows), "expected")
