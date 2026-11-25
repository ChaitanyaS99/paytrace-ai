# PayTrace AI

**Detecting invisible wage loss and payment manipulation for freelancers, gig workers, and independent contractors.**

Upload your own payment records (CSV, JSON, or XLSX), or answer a short questionnaire, and PayTrace AI reconciles what you expected against what you received. It flags potential discrepancies with plain-language reasons, shows explainable payment-risk indicators per payer, and produces a downloadable reconciliation report.

> **Privacy:** nothing you upload is stored. Files are processed in memory during your session and discarded when you close the tab.
>
> **Not legal advice:** PayTrace AI identifies *potential discrepancies* for your review. It does not determine that any law or contract was violated.

Built by Chaitanya (lead developer) for the Chicago Education Advocacy Cooperative (ChiEAC).

## Status

| Milestone | Status |
|---|---|
| 1. Data schema and ingestion | In progress |
| 2. Reconciliation engine | Not started |
| 3. Risk scoring | Not started |
| 4. Streamlit app and reports | Not started |

## Quick start

```bash
git clone https://github.com/<your-username>/paytrace-ai.git
cd paytrace-ai
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest
```

## Project layout

```
paytrace/
  schema.py      canonical tables (expected, received, adjustments) + validation
  ingest.py      CSV/JSON/XLSX readers, column mapper, questionnaire   (next)
  synth.py       synthetic data generator with injected patterns        (next)
  reconcile.py   matcher + detection rules                              (planned)
  features.py    transaction and payer features                         (planned)
  models.py      anomaly detection, Payment Risk Score, change points   (planned)
  report.py      PDF / XLSX / CSV reports                               (planned)
app/             Streamlit app                                          (planned)
tests/           pytest suite
```

## Data model

All inputs are converted to three tables. Required columns are in **bold**.

| Table | Columns |
|---|---|
| `expected` | **expected_id, payer, expected_amount, due_date**, work_period_start, work_period_end, description, rate, units, agreed_fee_pct, reference |
| `received` | **payment_id, payer, payment_date, net_amount**, gross_amount, fee_amount, reference, memo |
| `adjustments` | **adjustment_id, payer, date, type, amount**, disclosed, reference, memo |

`adjustments.type` is one of `fee, deduction, chargeback, bonus, correction`; `disclosed` is `yes, no, unknown`.

## Known limitations

- Trained and evaluated on synthetic data only; metrics describe synthetic performance.
- v1 matches one expected item to one payment. Batched or split payments may produce extra flags.
