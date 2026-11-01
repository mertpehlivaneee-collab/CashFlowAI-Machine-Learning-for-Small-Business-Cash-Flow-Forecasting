# Preprocessing Specification

## Scope

This specification freezes the first implementation design but does not
implement it. The initial modelling pipeline uses only `customers.parquet` and
`transactions.parquet`.

The other six tables are excluded from initial preprocessing. Their roles,
temporal limitations and optional-review conditions are recorded in
[the table usage decision](table_usage_decision.md).

## Required input columns

### Customers

| Column | Type | Required use |
| --- | --- | --- |
| `client_id` | string | Customer key and deterministic partition assignment |
| `segment` | string | Exact Private eligibility filter |

No other customer column enters the initial model. Demographics, legal-entity
code, region, household data and corporate-group fields are not used.

### Transactions

| Column | Type | Required use |
| --- | --- | --- |
| `client_id_fk` | string | Customer linkage |
| `book_date` | timestamp | Week assignment |
| `amount_eur` | double | Monetary aggregation |
| `dc_indicator` | string | Credit/debit classification |
| `txn_id` | string | Duplicate and integrity validation only |

`amount_orig` and `trx_ccy` are retained for validation but are not converted
again; `amount_eur` is the specified monetary field. Other transaction
attributes may support later feature specifications only after separate
leakage review.

## Type and null handling

- Require string identifiers, a timestamp-compatible booking date, a floating
  amount and the exact `C`/`D` direction values.
- Reject unsupported direction codes; do not guess their sign.
- Reject null or blank customer references.
- Reject null, zero or negative `amount_eur` values under the observed source
  contract rather than silently replacing them.
- Reject null booking dates.
- Do not impute missing customer attributes into model features.
- Treat a complete calendar week with no transactions as zero observed
  credits, zero observed debits and zero net flow.
- Do not interpret zero activity as missing source data without external
  evidence.
- Do not clip the target. Any predictor winsorisation must be fitted on the
  training partition and documented separately.

## Date normalization

- Interpret source dates as calendar dates without converting to a timezone.
- Retain only dates from 2024-01-01 through 2025-12-31.
- Assign each row to the Monday-to-Sunday week containing its booking date.
- Exclude 2025-12-29 through 2025-12-31 from the complete-week panel.
- Do not forward-fill a partial week as if it were complete.

## Deduplication and referential integrity

- Verify that `customers.client_id` is non-null and unique.
- Verify that every included transaction customer reference exists in the
  customer table.
- Verify that every included customer is exactly `Private`.
- Check `txn_id` for nulls and duplicates among included eligible transactions.
- Check for exact duplicate transaction rows using all selected source fields.
- Do not silently drop duplicates. If duplicates are found, halt the affected
  preprocessing build and record the discrepancy for resolution.
- Do not use orphan transactions in the modelling panel.

## Weekly aggregation

For each eligible customer and each of the 104 complete calendar weeks:

```text
weekly_credit_eur = sum(amount_eur where dc_indicator == "C")
weekly_debit_eur  = sum(amount_eur where dc_indicator == "D")
weekly_net_eur    = weekly_credit_eur - weekly_debit_eur
```

- Materialise zero-flow calendar weeks after eligibility is fixed.
- Do not join raw transaction rows to later tables.
- Aggregate product or balance tables only to an explicit customer-period
  grain, after they are approved for use.
- Do not duplicate monthly values across weeks unless temporal availability is
  established.

## Past-only feature construction

All feature construction is past-only.

For origin week `t`, compute features using complete weeks up to and including
`t`:

- Lags: 1, 2, 4 and 8 weeks.
- Rolling means: 2, 4 and 8 weeks.
- Rolling standard deviation: 8 weeks.
- Rolling credit and debit sums: 2 and 4 weeks.
- Active-day and active-week counts.
- Calendar features available at the origin.

Rules:

- `target_net_eur` is the net flow for week `t+1`.
- Features may not use target-week transactions.
- Features may not use a monthly snapshot whose availability date is later
  than the origin.
- Early panel rows with insufficient history retain missing lag values and do
  not use backward-filled or future information.
- The same feature code path must be used for training, validation and test.

## Duplicate and join protection

- Do not join any one-to-many product, agreement, policy or balance table
  directly to the weekly panel.
- Pre-aggregate optional tables to customer-period values first.
- Apply explicit as-of joins with publication/availability lag.
- Assert that the final panel has exactly one row per customer and week.
- Assert that no customer appears in more than one partition.
- Do not treat monthly snapshot ownership as static historical ownership.

## Intermediate outputs

The later implementation may write the following ignored, non-versioned
artefacts:

| Artefact | Grain | Purpose |
| --- | --- | --- |
| `eligible_customers` | One row per eligible customer | Frozen membership and partition assignment |
| `weekly_transaction_summary` | One row per customer/week | Credits, debits, net and activity counts |
| `model_panel` | One row per eligible customer/forecast origin | Features and next-week target |
| `split_manifest` | One row per customer | Deterministic train/validation/test assignment |

These outputs must remain outside Git because they contain customer-level
records or identifiers.

## Validation tests for implementation

1. Customer identifiers are non-null and unique.
2. Segment filtering returns only exact Private rows.
3. Every included transaction references an eligible customer.
4. No out-of-window transaction enters the panel.
5. The complete-week period contains 104 Monday-to-Sunday weeks.
6. The 2025-12-29 to 2025-12-31 tail is excluded from target construction.
7. Weekly net equals weekly credits minus weekly debits.
8. Zero-activity weeks become explicit zero-flow rows.
9. Lag and rolling features end no later than the origin week.
10. No target-week information enters any predictor.
11. Customer partitions are disjoint and reproducible from the seed.
12. The processed panel has one row per customer and forecast origin.
13. Duplicate transaction IDs and exact duplicate rows are diagnosed, not
    silently removed.
14. Scaling and outlier parameters are fitted only on training data.
15. All methods are evaluated on identical validation and test target rows.

## Frozen decisions

- Target: next-week net bank-transaction cash flow in EUR.
- Week: Monday through Sunday.
- Complete-week end: 2025-12-28.
- Partial tail: excluded.
- Initial sources: `customers` and `transactions`.
- Eligibility: exact Private, at least 50 transactions, at least 26 active
  weeks, at least 180 observed calendar days and activity in both years.
- Expected eligible population: 189,608 customers.
- Seed: `202401`.
- Partition strategy: customer-disjoint with deterministic assignment; exact
  ratios remain an implementation configuration decision.
- Baselines: at least two simple methods.
- Metrics: MAE and RMSE.
- Reporting: overall and per-customer error distributions.
