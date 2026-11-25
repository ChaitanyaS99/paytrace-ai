"""Generate synthetic payment histories for development and testing.

Writes expected, received and adjustments tables, plus labels.csv (one row per
known discrepancy) and payers.csv (one row per worker-payer pair).

Usage:
    python -m paytrace.synth --workers 300 --months 12 --seed 42 --out data/synth
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PATTERNS = (
    "missing_payment",
    "partial_payment",
    "late_payment",
    "unexplained_deduction",
    "fee_creep",
    "rate_erosion",
    "rounding_down",
    "duplicate_deduction",
    "unmatched_deposit",
)

# Per-item event probabilities for problem payers
PROBLEM_RATES = {
    "missing_payment": 0.15,
    "partial_payment": 0.25,
    "late_payment": 0.40,
    "unexplained_deduction": 0.20,
    "duplicate_deduction": 0.12,
}
# Occasional one-off events for normal payers
BACKGROUND_RATES = {
    "missing_payment": 0.004,
    "partial_payment": 0.01,
    "late_payment": 0.03,
    "unexplained_deduction": 0.005,
}
GRACE_DAYS = 14  # items due this close to the end date are never marked missing

_PREFIX = ["North", "Blue", "Summit", "Bright", "Metro", "Lake", "Prairie", "Iron", "Cedar", "Union",
           "Harbor", "Pixel", "Golden", "Red", "Maple", "Atlas", "Nova", "Swift", "Civic", "Loop"]
_SUFFIX = ["Media", "Labs", "Studio", "Partners", "Works", "Digital", "Group", "Design", "Health", "Logistics"]
_PLATFORMS = ["DashRun", "GigNest", "TaskHub", "QuickCart", "RideLoop", "FreelanceBay", "StudioShift", "ShiftUp"]


@dataclass
class SynthConfig:
    workers: int = 300
    months: int = 12
    start: str = "2025-11-01"
    seed: int = 42
    problem_payer_rate: float = 0.07
    inject: bool = True
    background: bool = True
    unmatched_rate: float = 0.5  # mean unmatched deposits per worker


class _Builder:
    def __init__(self, cfg: SynthConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.start = pd.Timestamp(cfg.start)
        self.as_of = self.start + pd.DateOffset(months=cfg.months)
        self.expected, self.received, self.adjustments = [], [], []
        self.labels, self.payers = [], []
        self._n = {"E": 0, "P": 0, "A": 0}

    def _id(self, kind: str, worker: str) -> str:
        self._n[kind] += 1
        return f"{worker}-{kind}{self._n[kind]:06d}"

    def _label(self, worker, payer, pattern, date, problem, eid=None, pid=None, aid=None):
        self.labels.append(dict(worker_id=worker, payer=payer, pattern=pattern, date=date.date(),
                                expected_id=eid, payment_id=pid, adjustment_id=aid,
                                is_problem_payer=problem))

    def _payer_profile(self, used: set) -> dict:
        r = self.rng
        kind = "platform" if r.random() < 0.35 else "client"
        while True:
            name = (r.choice(_PLATFORMS) if kind == "platform"
                    else f"{r.choice(_PREFIX)} {r.choice(_SUFFIX)}")
            if name not in used:
                used.add(name)
                break
            kind = "client"
        if kind == "platform":
            return dict(name=name, kind=kind, freq_days=7, terms=int(r.choice([0, 7])),
                        fee_pct=round(float(r.uniform(0.05, 0.25)), 3),
                        rate=round(float(r.lognormal(np.log(20), 0.25)), 2), units_mu=np.log(25))
        return dict(name=name, kind=kind, freq_days=int(r.choice([14, 30, 30])),
                    terms=int(r.choice([0, 15, 30, 30, 45])),
                    fee_pct=float(r.choice([0.0, 0.0, 0.029])),
                    rate=round(float(r.lognormal(np.log(55), 0.35)), 2), units_mu=np.log(30))

    def build(self) -> dict[str, pd.DataFrame]:
        for w in range(1, self.cfg.workers + 1):
            self._worker(f"W{w:04d}")
        return self._frames()

    def _worker(self, worker: str):
        r, cfg = self.rng, self.cfg
        used: set = set()
        for _ in range(int(r.integers(3, 11))):
            p = self._payer_profile(used)
            problem = cfg.inject and r.random() < cfg.problem_payer_rate
            behaviours = set()
            if problem:
                options = ["missing_payment", "partial_payment", "late_payment", "unexplained_deduction",
                           "duplicate_deduction", "rate_erosion", "rounding_down"]
                if p["fee_pct"] > 0:
                    options.append("fee_creep")
                behaviours = set(r.choice(options, size=int(r.integers(1, 4)), replace=False))
            self.payers.append(dict(worker_id=worker, payer=p["name"], kind=p["kind"], terms_days=p["terms"],
                                    agreed_fee_pct=p["fee_pct"], is_problem_payer=problem,
                                    behaviours=";".join(sorted(behaviours))))
            self._payer_history(worker, p, problem, behaviours)

        if cfg.inject:
            for _ in range(int(r.poisson(cfg.unmatched_rate))):
                self._unmatched_deposit(worker, sorted(used))

    def _payer_history(self, worker, p, problem, behaviours):
        r = self.rng
        span = (self.as_of - self.start).days
        # Trend patterns begin in the middle third of the period
        trend_start = self.start + pd.Timedelta(days=int(r.integers(span // 3, 2 * span // 3)))
        creep = float(r.uniform(0.02, 0.05))
        erosion = float(r.uniform(0.01, 0.025))  # per month
        for b in ("fee_creep", "rate_erosion", "rounding_down"):
            if b in behaviours:
                self._label(worker, p["name"], b, trend_start if b != "rounding_down" else self.start, problem)

        day = self.start + pd.Timedelta(days=int(r.integers(0, p["freq_days"])))
        while day < self.as_of:
            self._item(worker, p, problem, behaviours, day, trend_start, creep, erosion)
            day += pd.Timedelta(days=p["freq_days"])

    def _item(self, worker, p, problem, behaviours, invoice_date, trend_start, creep, erosion):
        r = self.rng
        units = round(float(r.lognormal(p["units_mu"], 0.3)), 1)
        expected_amount = round(p["rate"] * units, 2)
        due = invoice_date + pd.Timedelta(days=p["terms"])
        eid = self._id("E", worker)
        ref = f"INV-{eid[-6:]}"
        self.expected.append(dict(worker_id=worker, expected_id=eid, payer=p["name"],
                                  expected_amount=expected_amount, due_date=due.date(),
                                  work_period_start=(invoice_date - pd.Timedelta(days=p["freq_days"] - 1)).date(),
                                  work_period_end=invoice_date.date(), description=f"{p['kind']} work",
                                  rate=p["rate"], units=units, agreed_fee_pct=p["fee_pct"], reference=ref))

        def happens(pattern: str) -> bool:
            if pattern in behaviours:
                return r.random() < PROBLEM_RATES[pattern]
            if self.cfg.background and not problem and pattern in BACKGROUND_RATES:
                return r.random() < BACKGROUND_RATES[pattern]
            return False

        # Paid slightly before the due date, plus 0-3 days of bank processing
        early = int(r.integers(0, max(p["terms"] // 3, 1) + 1))
        pay_date = due - pd.Timedelta(days=early) + pd.Timedelta(days=int(r.integers(0, 4)))
        events = []
        if happens("late_payment"):
            pay_date = due + pd.Timedelta(days=int(r.integers(10, 61)) if problem else int(r.integers(8, 21)))
            events.append("late_payment")

        if happens("missing_payment") and due + pd.Timedelta(days=GRACE_DAYS) < self.as_of:
            self._label(worker, p["name"], "missing_payment", due, problem, eid=eid)
            return
        if pay_date > self.as_of:
            return  # not yet paid

        gross = expected_amount
        if "rate_erosion" in behaviours and invoice_date >= trend_start:
            months_in = (invoice_date - trend_start).days / 30.4
            gross = round(gross * (1 - erosion) ** months_in, 2)
        fee_pct = p["fee_pct"] + (creep if "fee_creep" in behaviours and invoice_date >= trend_start else 0.0)
        fee = round(gross * fee_pct, 2)
        net = gross - fee
        pid = self._id("P", worker)
        adj_rows = []

        if happens("partial_payment"):
            short = float(r.uniform(0.05, 0.40)) if problem else float(r.uniform(0.05, 0.15))
            gross = round(gross * (1 - short), 2)
            fee = round(gross * fee_pct, 2)
            net = gross - fee
            events.append("partial_payment")
        if happens("unexplained_deduction"):
            amt = round(gross * float(r.uniform(0.02, 0.10)), 2)
            net -= amt
            adj_rows.append(("deduction", amt, "no", pay_date, "unexplained_deduction"))
        if "duplicate_deduction" in behaviours and r.random() < PROBLEM_RATES["duplicate_deduction"]:
            amt = round(float(r.uniform(5, 40)), 2)
            net -= 2 * amt
            adj_rows.append(("chargeback", amt, "yes", pay_date, None))
            adj_rows.append(("chargeback", amt, "yes", pay_date + pd.Timedelta(days=int(r.integers(1, 8))),
                             "duplicate_deduction"))
        if "rounding_down" in behaviours and r.random() < 0.8:
            net -= float(r.uniform(0.01, 2.99))

        # Disclosed adjustments; these are legitimate and not labeled
        if r.random() < 0.03:
            amt = round(float(r.uniform(10, 60)), 2)
            gross = round(gross + amt, 2)  # a bonus is part of gross pay
            net += amt
            adj_rows.append(("bonus", amt, "yes", pay_date, None))
        if r.random() < 0.02:
            amt = round(float(r.uniform(5, 30)), 2)
            net -= amt
            adj_rows.append(("chargeback", amt, "yes", pay_date, None))

        net = round(net, 2)
        self.received.append(dict(worker_id=worker, payment_id=pid, payer=p["name"],
                                  payment_date=pay_date.date(), gross_amount=gross, fee_amount=fee,
                                  net_amount=net, reference=ref if r.random() < 0.7 else None,
                                  memo=f"Payment from {p['name']}"))
        for pattern in events:
            self._label(worker, p["name"], pattern, pay_date, problem, eid=eid, pid=pid)
        for typ, amt, disclosed, d, pattern in adj_rows:
            aid = self._id("A", worker)
            self.adjustments.append(dict(worker_id=worker, adjustment_id=aid, payer=p["name"], date=d.date(),
                                         type=typ, amount=amt, disclosed=disclosed, reference=pid,
                                         memo=f"{typ} on {pid}"))
            if pattern:
                self._label(worker, p["name"], pattern, d, problem, eid=eid, pid=pid, aid=aid)

    def _unmatched_deposit(self, worker, payer_names):
        r = self.rng
        payer = str(r.choice(payer_names))
        d = self.start + pd.Timedelta(days=int(r.integers(0, (self.as_of - self.start).days)))
        amt = round(float(r.lognormal(np.log(150), 0.6)), 2)
        pid = self._id("P", worker)
        self.received.append(dict(worker_id=worker, payment_id=pid, payer=payer, payment_date=d.date(),
                                  gross_amount=amt, fee_amount=0.0, net_amount=amt, reference=None,
                                  memo="Deposit"))
        self._label(worker, payer, "unmatched_deposit", d, False, pid=pid)

    def _frames(self) -> dict[str, pd.DataFrame]:
        cols = {
            "labels": ["worker_id", "payer", "pattern", "date", "expected_id", "payment_id",
                       "adjustment_id", "is_problem_payer"],
            "adjustments": ["worker_id", "adjustment_id", "payer", "date", "type", "amount",
                            "disclosed", "reference", "memo"],
        }
        out = {
            "expected": pd.DataFrame(self.expected),
            "received": pd.DataFrame(self.received),
            "adjustments": pd.DataFrame(self.adjustments, columns=cols["adjustments"]),
            "labels": pd.DataFrame(self.labels, columns=cols["labels"]),
            "payers": pd.DataFrame(self.payers),
        }
        out["received"] = out["received"].sort_values(["worker_id", "payment_date", "payment_id"]).reset_index(drop=True)
        return out


SAMPLE_PAYERS = [
    # name, kind, freq_days, terms, fee_pct, rate, behaviours
    ("Metro Labs", "client", 30, 30, 0.0, 65.0, set()),
    ("Lake Works", "client", 30, 15, 0.0, 55.0, set()),
    ("Pixel Studio", "client", 14, 15, 0.029, 48.0, set()),
    ("Atlas Design", "client", 30, 30, 0.0, 60.0, {"late_payment", "missing_payment"}),
    ("Cedar Health", "client", 30, 45, 0.0, 70.0, {"partial_payment"}),
    ("Summit Media", "client", 14, 15, 0.029, 52.0, {"rounding_down"}),
    ("DashRun", "platform", 7, 7, 0.15, 21.0, {"fee_creep", "unexplained_deduction"}),
    ("TaskHub", "platform", 7, 0, 0.20, 19.0, {"rate_erosion", "duplicate_deduction"}),
]


def make_sample(seed: int = 2026, months: int = 12, start: str = "2025-11-01") -> dict[str, pd.DataFrame]:
    """Build the bundled sample: one worker, eight payers, every pattern represented."""
    for s in range(seed, seed + 200):
        b = _Builder(SynthConfig(workers=1, months=months, start=start, seed=s, background=False))
        worker = "W0001"
        for name, kind, freq, terms, fee, rate, behaviours in SAMPLE_PAYERS:
            p = dict(name=name, kind=kind, freq_days=freq, terms=terms, fee_pct=fee, rate=rate,
                     units_mu=np.log(25) if kind == "platform" else np.log(30))
            problem = bool(behaviours)
            b.payers.append(dict(worker_id=worker, payer=name, kind=kind, terms_days=terms, agreed_fee_pct=fee,
                                 is_problem_payer=problem, behaviours=";".join(sorted(behaviours))))
            b._payer_history(worker, p, problem, behaviours)
        names = [p[0] for p in SAMPLE_PAYERS]
        for _ in range(2):
            b._unmatched_deposit(worker, names)
        frames = b._frames()
        if set(PATTERNS) <= set(frames["labels"]["pattern"]):
            return {k: v.drop(columns="worker_id") for k, v in frames.items()}
    raise RuntimeError("Could not produce a sample containing every pattern")


def write_sample(out_dir: str | Path = "samples/freelancer") -> None:
    f = make_sample()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("expected", "received", "adjustments"):
        f[name].to_csv(out / f"{name}.csv", index=False)


def generate(cfg: SynthConfig | None = None, **kwargs) -> dict[str, pd.DataFrame]:
    """Generate synthetic tables. Pass a SynthConfig or keyword overrides."""
    cfg = cfg or SynthConfig(**kwargs)
    return _Builder(cfg).build()


def write(frames: dict[str, pd.DataFrame], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(out / f"{name}.csv", index=False)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic PayTrace data.")
    ap.add_argument("--workers", type=int, default=300)
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--start", default="2025-11-01")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--problem-rate", type=float, default=0.07)
    ap.add_argument("--clean", action="store_true", help="generate histories with no discrepancies")
    ap.add_argument("--out", default="data/synth")
    a = ap.parse_args(argv)
    cfg = SynthConfig(workers=a.workers, months=a.months, start=a.start, seed=a.seed,
                      problem_payer_rate=a.problem_rate, inject=not a.clean, background=not a.clean)
    frames = generate(cfg)
    write(frames, a.out)
    p = frames["payers"]
    print(f"Wrote {a.out}: {len(frames['expected'])} expected, {len(frames['received'])} received, "
          f"{len(frames['adjustments'])} adjustments, {len(frames['labels'])} labeled events; "
          f"{p['is_problem_payer'].mean():.1%} problem payers across {len(p)} payer relationships.")


if __name__ == "__main__":
    main()
