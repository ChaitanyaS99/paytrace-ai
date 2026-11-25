# Sample Data

`samples/freelancer/` contains twelve months of payment records for a freelancer working with eight clients and platforms.

| File | Contents |
|---|---|
| `expected.csv` | Invoices and amounts owed |
| `received.csv` | Payments received |
| `adjustments.csv` | Fees, deductions, chargebacks, and bonuses |

Additional datasets can be generated for testing:

```bash
python -m paytrace.synth --workers 300 --months 12 --seed 42 --out data/synth
```

Run `python -m paytrace.synth --help` for all options.
