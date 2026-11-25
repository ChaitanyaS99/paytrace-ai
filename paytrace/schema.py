"""Table definitions and validation.

All inputs are normalized into three tables:

    expected     amounts owed to the worker
    received     payments received
    adjustments  fees, deductions, chargebacks, bonuses and corrections

coerce() converts types and fills derivable values. validate() returns a list
of readable problems instead of raising, so they can be shown to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

ADJUSTMENT_TYPES = {"fee", "deduction", "chargeback", "bonus", "correction"}
DISCLOSED_VALUES = {"yes", "no", "unknown"}


@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # "str", "float", "date"
    required: bool = True
    non_negative: bool = False


@dataclass(frozen=True)
class TableSpec:
    name: str
    id_column: str
    columns: list[Column] = field(default_factory=list)

    @property
    def required(self) -> list[str]:
        return [c.name for c in self.columns if c.required]

    @property
    def all(self) -> list[str]:
        return [c.name for c in self.columns]


EXPECTED = TableSpec(
    name="expected",
    id_column="expected_id",
    columns=[
        Column("expected_id", "str"),
        Column("payer", "str"),
        Column("expected_amount", "float", non_negative=True),
        Column("due_date", "date"),
        Column("work_period_start", "date", required=False),
        Column("work_period_end", "date", required=False),
        Column("description", "str", required=False),
        Column("rate", "float", required=False, non_negative=True),
        Column("units", "float", required=False, non_negative=True),
        Column("agreed_fee_pct", "float", required=False, non_negative=True),
        Column("reference", "str", required=False),
    ],
)

RECEIVED = TableSpec(
    name="received",
    id_column="payment_id",
    columns=[
        Column("payment_id", "str"),
        Column("payer", "str"),
        Column("payment_date", "date"),
        Column("net_amount", "float"),
        Column("gross_amount", "float", required=False),
        Column("fee_amount", "float", required=False, non_negative=True),
        Column("reference", "str", required=False),
        Column("memo", "str", required=False),
    ],
)

ADJUSTMENTS = TableSpec(
    name="adjustments",
    id_column="adjustment_id",
    columns=[
        Column("adjustment_id", "str"),
        Column("payer", "str"),
        Column("date", "date"),
        Column("type", "str"),
        Column("amount", "float", non_negative=True),
        Column("disclosed", "str", required=False),
        Column("reference", "str", required=False),
        Column("memo", "str", required=False),
    ],
)

SPECS: dict[str, TableSpec] = {s.name: s for s in (EXPECTED, RECEIVED, ADJUSTMENTS)}


def get_spec(table: str) -> TableSpec:
    if table not in SPECS:
        raise ValueError(f"Unknown table '{table}'. Use one of: {', '.join(SPECS)}")
    return SPECS[table]


def empty(table: str) -> pd.DataFrame:
    """An empty, correctly typed frame for a table."""
    return coerce(pd.DataFrame(columns=get_spec(table).all), table)


def coerce(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Return a typed copy with optional columns added and derivable values filled.
    Unreadable values become NaN/NaT and are reported by validate()."""
    spec = get_spec(table)
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]

    for col in spec.columns:
        if col.name not in out.columns:
            if col.required:
                continue
            out[col.name] = pd.NA
        s = out[col.name]
        if col.kind == "float":
            if not pd.api.types.is_numeric_dtype(s):
                s = s.astype(str).str.replace(r"[,$\s]", "", regex=True).replace({"": None, "nan": None, "None": None, "<NA>": None})
            out[col.name] = pd.to_numeric(s, errors="coerce").astype("float64")
        elif col.kind == "date":
            out[col.name] = pd.to_datetime(s, errors="coerce", format="mixed").dt.normalize()
        else:
            out[col.name] = s.astype("string").str.strip()

    if table == "received":
        gross, fee, net = out.get("gross_amount"), out.get("fee_amount"), out.get("net_amount")
        if net is not None and gross is not None and fee is not None:
            out["net_amount"] = net.fillna(gross - fee)
            out["gross_amount"] = gross.fillna(out["net_amount"] + fee)
        if gross is not None and "net_amount" in out:
            out["fee_amount"] = out["fee_amount"].fillna(out["gross_amount"] - out["net_amount"])

    if table == "adjustments":
        if "type" in out.columns:
            out["type"] = out["type"].str.lower()
        out["disclosed"] = out["disclosed"].str.lower().fillna("unknown")

    if spec.id_column in out.columns:
        out[spec.id_column] = out[spec.id_column].astype("string")

    ordered = [c for c in spec.all if c in out.columns]
    extra = [c for c in out.columns if c not in spec.all]
    return out[ordered + extra]


def validate(df: pd.DataFrame, table: str, max_examples: int = 3) -> list[str]:
    """Return a list of problems with a coerced table. An empty list means it is valid."""
    spec = get_spec(table)
    problems: list[str] = []

    missing = [c for c in spec.required if c not in df.columns]
    if missing:
        problems.append(f"{table}: missing required column(s): {', '.join(missing)}")
        return problems

    if df.empty:
        problems.append(f"{table}: no rows found")
        return problems

    def rows(mask: pd.Series) -> str:
        idx = [str(i + 2) for i in mask[mask].index[:max_examples]]  # spreadsheet row numbers
        more = "" if mask.sum() <= max_examples else f" (+{mask.sum() - max_examples} more)"
        return ", ".join(idx) + more

    for col in spec.columns:
        if col.name not in df.columns:
            continue
        s = df[col.name]
        if col.required:
            bad = s.isna()
            if bad.any():
                label = {"date": "missing or unreadable date", "float": "missing or non-numeric value"}.get(col.kind, "empty value")
                problems.append(f"{table}.{col.name}: {label} in row(s) {rows(bad)}")
        if col.non_negative and col.kind == "float":
            bad = s.notna() & (s < 0)
            if bad.any():
                problems.append(f"{table}.{col.name}: negative value in row(s) {rows(bad)}")

    ids = df[spec.id_column]
    dup = ids.notna() & ids.duplicated(keep=False)
    if dup.any():
        problems.append(f"{table}.{spec.id_column}: duplicate id in row(s) {rows(dup)}")

    if table == "received" and "gross_amount" in df.columns:
        bad = df["gross_amount"].notna() & (df["net_amount"] > df["gross_amount"] + 0.005)
        if bad.any():
            problems.append(f"received: net_amount is larger than gross_amount in row(s) {rows(bad)}")

    if table == "adjustments":
        bad = df["type"].notna() & ~df["type"].isin(ADJUSTMENT_TYPES)
        if bad.any():
            problems.append(f"adjustments.type: must be one of {sorted(ADJUSTMENT_TYPES)}; check row(s) {rows(bad)}")
        if "disclosed" in df.columns:
            bad = df["disclosed"].notna() & ~df["disclosed"].isin(DISCLOSED_VALUES)
            if bad.any():
                problems.append(f"adjustments.disclosed: must be yes, no or unknown; check row(s) {rows(bad)}")

    if table == "expected" and "work_period_end" in df.columns:
        bad = df["work_period_start"].notna() & df["work_period_end"].notna() & (df["work_period_end"] < df["work_period_start"])
        if bad.any():
            problems.append(f"expected: work_period_end is before work_period_start in row(s) {rows(bad)}")

    return problems


def load(df: pd.DataFrame, table: str) -> tuple[pd.DataFrame, list[str]]:
    """Coerce and validate a table."""
    clean = coerce(df, table)
    return clean, validate(clean, table)
