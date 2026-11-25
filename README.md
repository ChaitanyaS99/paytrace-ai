# PayTrace AI

Payment auditing for freelancers, gig workers, and independent contractors.

PayTrace AI compares what a worker was owed with what they were paid and identifies potential payment discrepancies.

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

## Supported inputs

- CSV, JSON, and Excel (.xlsx) files
- Exports from PayPal, Stripe, Upwork, and DoorDash, and standard invoice spreadsheets
- A guided questionnaire for workers without invoice records

## Documentation

- [Detection patterns](PATTERNS.md)
- [Sample data](docs/sample-data.md)

## Disclaimer

PayTrace AI identifies potential payment discrepancies for the user's review. It does not provide legal advice and does not determine whether any law or contract has been violated.

## Ownership

Copyright © 2026 Chicago Education Advocacy Cooperative (ChiEAC). All rights reserved.

Project Lead Developer: Chaitanya Suralkar
