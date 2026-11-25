# PayTrace AI

Payment auditing for freelancers, gig workers, and independent contractors.

PayTrace AI compares what a worker was owed with what they were actually paid and identifies potential payment discrepancies.

## Getting started

Requires Python 3.10 or later.

```bash
git clone https://github.com/ChaitanyaS99/paytrace-ai.git
cd paytrace-ai
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest
```

## Sample data

`samples/freelancer/` contains a year of payment records for a freelancer with eight payers, including platform and direct-client work:

| File | Contents |
|---|---|
| `expected.csv` | Invoices and amounts owed |
| `received.csv` | Payments received, with gross, fee, and net amounts |
| `adjustments.csv` | Fees, chargebacks, deductions, and bonuses |

Five payers show payment issues covering all patterns described in [PATTERNS.md](PATTERNS.md); the other three are paid normally. `answer_key.csv` lists each issue for testing.

Larger datasets can be generated with `python -m paytrace.synth --help`. See [docs/SYNTH_DESIGN.md](docs/SYNTH_DESIGN.md).

## Disclaimer

PayTrace AI identifies potential payment discrepancies for the user's review. It does not provide legal advice and does not determine whether any law or contract has been violated.

## Ownership

Copyright © 2026 Chicago Education Advocacy Cooperative (ChiEAC). All rights reserved.

Project Lead Developer: Chaitanya Suralkar
