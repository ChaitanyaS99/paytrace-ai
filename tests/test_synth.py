import io
from pathlib import Path

import pandas as pd
import pytest

from paytrace import schema, synth


@pytest.fixture(scope="module")
def frames():
    return synth.generate(workers=60, months=12, seed=7)


def test_same_seed_same_output():
    a = synth.generate(workers=5, seed=1)
    b = synth.generate(workers=5, seed=1)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_different_seed_differs():
    a = synth.generate(workers=5, seed=1)["expected"]
    b = synth.generate(workers=5, seed=2)["expected"]
    assert not a.equals(b)


@pytest.mark.parametrize("table", ["expected", "received", "adjustments"])
def test_tables_pass_schema(frames, table):
    _, problems = schema.load(frames[table], table)
    assert problems == []


def test_labels_reference_real_ids(frames):
    labels = frames["labels"]
    for col, table, id_col in [("expected_id", "expected", "expected_id"),
                               ("payment_id", "received", "payment_id"),
                               ("adjustment_id", "adjustments", "adjustment_id")]:
        ids = labels[col].dropna()
        assert ids.isin(frames[table][id_col]).all(), col


def test_missing_payments_have_no_payment(frames):
    missing = frames["labels"].query("pattern == 'missing_payment'")
    paid_refs = frames["received"]["reference"].dropna()
    expected = frames["expected"].set_index("expected_id")
    refs = expected.loc[missing["expected_id"], "reference"]
    assert not refs.isin(paid_refs).any()


def test_late_payments_are_late(frames):
    late = frames["labels"].query("pattern == 'late_payment'")
    exp = frames["expected"].set_index("expected_id")["due_date"]
    rec = frames["received"].set_index("payment_id")["payment_date"]
    days = (pd.to_datetime(rec.loc[late["payment_id"]]).values
            - pd.to_datetime(exp.loc[late["expected_id"]]).values).astype("timedelta64[D]").astype(int)
    assert (days >= 8).all()


def test_problem_payer_rate_is_rare(frames):
    rate = frames["payers"]["is_problem_payer"].mean()
    assert 0.02 < rate < 0.15


def test_all_patterns_can_appear():
    labels = synth.generate(workers=200, seed=3)["labels"]
    assert set(synth.PATTERNS) <= set(labels["pattern"])


def test_clean_mode_has_no_events():
    f = synth.generate(workers=20, seed=5, inject=False, background=False)
    assert f["labels"].empty
    assert not f["payers"]["is_problem_payer"].any()
    assert (f["adjustments"]["disclosed"] == "yes").all()


def test_cli_writes_files(tmp_path):
    synth.main(["--workers", "3", "--out", str(tmp_path)])
    for name in ["expected", "received", "adjustments", "labels", "payers"]:
        assert (tmp_path / f"{name}.csv").exists()


def test_sample_contains_every_pattern_and_clean_payers():
    f = synth.make_sample()
    assert set(synth.PATTERNS) <= set(f["labels"]["pattern"])
    clean = {p[0] for p in synth.SAMPLE_PAYERS if not p[6]}
    assert clean and not (set(f["labels"].query("pattern != 'unmatched_deposit'")["payer"]) & clean)
    for table in ("expected", "received", "adjustments"):
        assert schema.load(f[table], table)[1] == []


def test_committed_sample_matches_generator():
    folder = Path(__file__).resolve().parents[1] / "samples" / "freelancer"
    f = synth.make_sample()
    for name in ("expected", "received", "adjustments"):
        on_disk = pd.read_csv(folder / f"{name}.csv")
        fresh = pd.read_csv(io.StringIO(f[name].to_csv(index=False)))
        pd.testing.assert_frame_equal(on_disk, fresh)
