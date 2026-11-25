# Detection Patterns

PayTrace AI checks payment records for nine patterns. Each result is a potential discrepancy for the user to review, together with the reason and the records behind it. It is not a finding that any law or contract was violated.

Unless stated otherwise, the default tolerance is 1% of the expected amount or $5, whichever is larger.

## 1. Missing payment
An expected item has no matching payment, and the due date plus a grace period has passed.

| expected_id | payer | expected_amount | due_date | matched payment |
|---|---|---|---|---|
| E101 | Metro Labs | $1,200.00 | 2026-03-01 | none (checked on 2026-03-20) |

Rule: no match after reference, amount-and-date, and fuzzy matching, and *today − due date > grace* (default 7 days).

## 2. Partial payment (shortfall)
A payment arrives, but for less than the amount owed.

| expected_id | expected | received (gross) | shortfall |
|---|---|---|---|
| E102 | $800.00 | $640.00 | $160.00 |

Rule: matched gross amount is below expected by more than tolerance.

## 3. Late payment
A payment arrives after the agreed due date.

| expected_id | due_date | payment_date | days late |
|---|---|---|---|
| E103 | 2026-03-15 | 2026-04-09 | 25 |

Rule: *days late = payment date − due date*. Severity: low 1–15, medium 16–45, high over 45 days. A small allowance for bank processing (default 3 days) prevents false flags from transfer delays.

## 4. Unexplained deduction
Less money arrived than gross minus the agreed fee, or a deduction appears that was never disclosed.

| payment | gross | agreed fee (10%) | expected net | actual net | unexplained |
|---|---|---|---|---|---|
| P201 | $500.00 | $50.00 | $450.00 | $418.00 | $32.00 |

Rule: *gross − net − agreed fee − disclosed adjustments* exceeds tolerance, or an adjustment of type deduction or chargeback has *disclosed ≠ yes*.

## 5. Fee creep
The fee percentage a payer charges rises over time.

| period | median fee % |
|---|---|
| Nov–Jan | 12.0% |
| May–Jul | 15.5% |

Rule: rolling 90-day median fee % rises by more than 1 percentage point versus the previous window. Needs at least 6 months of data.

## 6. Rate erosion
Effective pay per unit or per hour from a payer trends downward without an agreed change.

| month | units | gross | effective rate |
|---|---|---|---|
| Jan | 30 | $1,650 | $55.00 |
| Jun | 30 | $1,530 | $51.00 |

Rule: linear trend on effective rate per period is negative, and the total change exceeds 3% over the window. Needs at least 6 periods.

## 7. Rounding down
Many payments are a few cents or dollars short, always in the payer's favor.

| expected | received | residual |
|---|---|---|
| $412.50 | $411.00 | −$1.50 |
| $398.20 | $397.00 | −$1.20 |
| $405.75 | $404.00 | −$1.75 |

Rule: more than 60% of a payer's matched payments have a small negative residual (within tolerance), and the mean residual is negative. Needs at least 5 payments.

## 8. Duplicate deduction
The same fee or chargeback is applied twice.

| adjustment_id | date | type | amount |
|---|---|---|---|
| A301 | 2026-04-02 | chargeback | $25.00 |
| A302 | 2026-04-05 | chargeback | $25.00 |

Rule: two adjustments from the same payer with the same amount and type within 7 days.

## 9. Unmatched deposit (informational)
Money arrived with no expected record. It usually means an invoice is missing from the user's records.

| payment_id | payer | date | amount | matched expected item |
|---|---|---|---|---|
| P401 | Lake Works | 2026-02-11 | $150.00 | none |

Rule: a received payment with no match. Shown separately so the user can add the missing expectation.


## Verification status

Every flag is labeled:

- Supported by both records: the files contain both the expected item and the payment (or its absence after the due date).
- Needs documentation: only one side is in the files, or the expectation came from the questionnaire.
