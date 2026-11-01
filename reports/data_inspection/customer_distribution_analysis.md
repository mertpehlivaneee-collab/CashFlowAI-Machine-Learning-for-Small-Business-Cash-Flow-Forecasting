# Customer Distribution and Activity Analysis

## Executive Summary

The customer universe contains 200,000 customers, of which 200,000 have at least one transaction and 0 have none. A provisional eligibility rule identifies 189,608 customers for later panel construction; no customer has yet been assigned to a model partition.

The analysis uses complete Monday-to-Sunday weeks. The final partial week is excluded from target and feature generation, while its transactions are reported separately.

## Customer Activity Distributions

| Measure | Customers/weeks | Min | Median | Mean | P90 | P95 | P99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Transactions per customer (all) | 200,000 | 12 | 587.0000 | 604.6333 | 1,002.0000 | 1,097.0000 | 1,292.0000 | 1,786 |
| Transactions per active customer | 200,000 | 12 | 587.0000 | 604.6333 | 1,002.0000 | 1,097.0000 | 1,292.0000 | 1,786 |
| Active transaction days | 200,000 | 11 | 383.0000 | 367.1996 | 520.0000 | 543.0000 | 580.0000 | 647 |
| Observed history days | 200,000 | 69 | 728.0000 | 689.4840 | 731.0000 | 731.0000 | 731.0000 | 731 |
| Active complete weeks | 200,000 | 8 | 103.0000 | 95.8080 | 104.0000 | 104.0000 | 104.0000 | 104 |
| Credit transactions per customer | 200,000 | 3 | 62.0000 | 64.5073 | 88.0000 | 95.0000 | 110.0000 | 146 |
| Debit transactions per customer | 200,000 | 5 | 522.0000 | 540.1260 | 925.0000 | 1,016.0000 | 1,207.0000 | 1,689 |

The observed history length is the inclusive number of calendar days between a customer's first and last transaction. Active weeks count only Monday-to-Sunday periods containing at least one transaction.

### First and last transaction dates

| Measure | Earliest | P05 | Median | P95 | Latest | Distinct dates |
| --- | --- | --- | --- | --- | --- | ---: |
| First transaction date | 2024-01-01 | 2024-01-01 | 2024-01-03 | 2025-01-11 | 2025-10-18 | 652 |
| Last transaction date | 2025-12-03 | 2025-12-26 | 2025-12-31 | 2025-12-31 | 2025-12-31 | 28 |

## Calendar and Weekly Activity

- Complete calendar weeks per customer: 104.
- Active customer-weeks: 19,161,610.
- Zero-activity customer-weeks in the full window: 1,638,390.
- Zero-activity weeks within each customer's observed span: 530,928.
- Partial-week transactions excluded from targets/features: 708,047.

Zero-activity weeks are retained as observed zero activity. They are not automatically labelled missing source data.

| Weekly active-cell measure | Count | Min | Median | Mean | P90 | P95 | P99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Transactions per active customer-week | 19,161,610 | 1 | 5.0000 | 6.2739 | 12.0000 | 14.0000 | 19.0000 | 43 |

## Weekly Net Cash-Flow Distribution

| Measure | Value |
| --- | ---: |
| Active customer-weeks | 19,161,610 |
| Negative net-flow weeks | 11,955,572 |
| Zero net-flow active weeks | 4,502 |
| Positive net-flow weeks | 7,201,536 |
| Exact minimum (EUR) | -14,957.2100 |
| Exact maximum (EUR) | 81,101.9900 |
| Exact mean (EUR) | 435.7918 |
| Sampled p25 (EUR) | -303.8700 |
| Sampled median (EUR) | -58.2600 |
| Sampled p75 (EUR) | 565.1100 |
| Sampled p95 (EUR) | 3,713.5500 |
| Sampled p99 (EUR) | 8,289.1000 |

Quantiles use a deterministic systematic sample. Sign counts, sums and extrema are exact aggregates.

## Credit and Debit Activity

- Customers with both credits and debits: 200,000.
- Credit-only customers: 0.
- Debit-only customers: 0.
- Customers with no transactions: 0.
- Customers active in both 2024 and 2025: 189,608.
- 2024 transactions: 54,462,693; 2025 transactions: 66,463,969.

### Year-over-year activity changes

| Activity pattern | Customers |
| --- | ---: |
| `active_2025_only` | 10,392 |
| `equal_transactions` | 1,474 |
| `fewer_transactions_2025` | 26,068 |
| `more_transactions_2025` | 162,066 |

The per-customer difference in transaction count (2025 minus 2024) has median 38.0000 and range -402 to 860.

## Transaction Amount Extremes

- Non-null transactions: 120,926,662.
- Exact amount range: EUR 0.0500 to 80,425.5800.
- Zero amounts: 0; negative amounts: 0.
- Amounts above EUR 1,000: 4,847,558.
- Amounts above EUR 5,000: 537,250.
- Amounts above EUR 10,000: 79,273.
- Sampled p99 amount: EUR 1,629.1471.

Extreme values are reported but are not clipped or removed. The target retains actual cash-flow semantics; any robust treatment would require a separately validated rule.

## Eligibility Sensitivity

| Minimum transactions | Eligible customers |
| ---: | ---: |
| 1 | 200,000 |
| 10 | 200,000 |
| 50 | 199,345 |
| 100 | 196,992 |
| 200 | 185,777 |
| 400 | 143,817 |

| Minimum active weeks | Eligible customers |
| ---: | ---: |
| 1 | 200,000 |
| 12 | 199,906 |
| 26 | 196,342 |
| 52 | 189,327 |
| 78 | 181,565 |

| Minimum observed history (days) | Eligible customers |
| ---: | ---: |
| 1 | 200,000 |
| 90 | 199,925 |
| 180 | 196,592 |
| 365 | 189,613 |
| 547 | 182,790 |

### Recommended provisional rule

- At least 50 transactions.
- At least 26 active weeks.
- At least 180 observed calendar days.
- Activity in both 2024 and 2025.
- Eligible customers: 189,608 of 200,000.

This rule is a specification for later panel construction and has not been applied to any model or output dataset.

## Limitations

- Zero transaction activity is treated as zero observed activity, not automatically as missing source data.
- Weekly net-flow quantiles use a deterministic bounded sample; exact sign counts, sums and extrema are retained.
- Exact transaction identifier uniqueness and counterparty-account distinctness remain deferred because their identifier spaces are unbounded for bounded-memory processing.
- The final weekly panel, eligibility assignment, split assignment, preprocessing pipeline and models have not been created.
- Synthetic data cannot establish performance on real customers.

Raw customer identifiers and transaction records are not included.
