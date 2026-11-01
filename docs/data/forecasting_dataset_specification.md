# Forecasting Dataset Specification

## Objective

The model will forecast next-week net bank-transaction cash flow for an
eligible Private-customer panel using a single global regression model.

It does not forecast an accounting cash-flow statement and does not infer an
account balance from transaction direction.

## Target

For customer `i` and complete week `t`:

```text
credits[i,t] = sum(transactions.amount_eur
                   where dc_indicator = C)
debits[i,t]  = sum(transactions.amount_eur
                   where dc_indicator = D)
net_flow[i,t] = credits[i,t] - debits[i,t]
target[i,t] = net_flow[i,t+1]
```

The target is measured in EUR. Negative net cash flow means that debits exceed
credits in that week. It is not evidence of insufficient account balance or an
overdraft.

## Observation window and week boundary

- Study window: 2024-01-01 through 2025-12-31.
- Week boundary: Monday 00:00 through the following Sunday 23:59:59.
- Complete-week period: 2024-01-01 through 2025-12-28, comprising 104 weeks.
- Partial tail: 2025-12-29 through 2025-12-31.
- The partial tail contains 708,047 transactions and is excluded from target
  and feature construction.
- The weekly panel uses calendar weeks even when a customer has no
  transactions. No-transaction weeks represent observed zero activity unless
  separate source-provenance evidence establishes missing data.

## Eligibility specification

The initial eligibility rule is:

- `customers.segment` is exactly `Private`.
- `client_id` is non-null.
- The customer has at least 50 transactions in the observation window.
- The customer has at least 26 active complete weeks.
- First-to-last transaction history spans at least 180 calendar days.
- The customer has transaction activity in both 2024 and 2025.

Observed result: **189,608 eligible customers out of 200,000**. This is a
preprocessing specification, not a final materialised customer list.

Sensitivity results demonstrate the effect of weakening or strengthening these
thresholds. The rule is deliberately conservative enough to provide historical
context across both years while retaining 94.8% of the customer population.

## Panel grain

The intended intermediate panel has one row per eligible customer and complete
forecast-origin week, with the following logical fields:

| Field group | Fields | Definition |
| --- | --- | --- |
| Identity | `customer_key`, `week_index`, `week_start`, `week_end` | Internal customer key and Monday-to-Sunday week |
| Current activity | `weekly_credit_eur`, `weekly_debit_eur`, `weekly_net_eur` | Aggregates for the feature week |
| Target | `target_week_start`, `target_week_end`, `target_net_eur` | Next complete week's net flow |
| Lag history | `lag_1_net`, `lag_2_net`, `lag_4_net`, `lag_8_net` | Past net-flow values at fixed lags |
| Rolling history | `rolling_2_mean`, `rolling_4_mean`, `rolling_8_mean`, `rolling_8_std` | Statistics ending at the current week |
| Flow history | `credit_sum_2`, `credit_sum_4`, `debit_sum_2`, `debit_sum_4` | Past inflow/outflow aggregates |
| Activity history | `active_day_count`, `active_week_count` | Activity evidence ending at the current week |
| Calendar | `week_of_year`, `month` | Calendar values known at forecast origin |

`customer_key` may be the source identifier internally but must not be
published in aggregate reports. No static demographic or product attribute is
required in the initial model.

The final processed panel must not be committed because it contains
customer-week records and may be large.

## Past-only feature timing

All feature construction is past-only. At the end of feature week `t`, only
information from week `t` and earlier may be used. The target is week `t+1`.

- Lag and rolling features must end no later than week `t`.
- Calendar features must describe the origin or target without using observed
  future values.
- Centering, scaling, imputation and outlier parameters must be fitted on the
  training partition only.
- Missing lookback values at the start of a customer's history remain missing;
  they are not backfilled.
- A feature from a monthly table would need an explicit publication timestamp
  or conservative as-of lag before it can enter the panel.

## Customer partitions

The split is customer-disjoint:

- Every customer belongs to exactly one of training, validation or test.
- All observable weeks for that customer remain in the assigned partition.
- A deterministic seed is required.
- The implementation will use seed `202401`.
- Exact ratios will be finalized in implementation; a 70/15/15 split is the
  working recommendation, subject to accepted implementation configuration.
- Partition assignment should be computed from customer identifiers using a
  stable hash or a sorted identifier list with a seeded generator, not from
  observed model errors.

The split measures generalization to previously unseen customers. It does not
establish generalization to an unseen future calendar year because customers
in all partitions may have observations from both 2024 and 2025.

## Common evaluation window

- The first usable target depends on the longest required feature window.
- With an eight-week lookback, training, validation and test comparisons should
  share the same eligible target weeks after the warm-up period.
- All methods must be evaluated on identical customer-week target rows within
  the validation and test partitions.
- The final complete target week ends on 2025-12-28.
- Per-customer error summaries must use only customers with at least one
  evaluable target row.

## Baselines and metrics

At least two simple baselines will be implemented before the global ML model:

1. Zero-forecast baseline: predict net cash flow of zero.
2. Previous-week baseline: forecast the most recent observed net cash flow.
3. Optional seasonal or rolling-mean baseline: forecast from historical
   same-season or recent-window information.

The global model and all baselines must use the same target rows for MAE and
RMSE comparison. Reporting will include:

- Overall MAE and RMSE.
- Per-customer MAE and RMSE distributions.
- Counts of customers improved or worsened relative to each baseline.
- Explicit treatment and reporting of extreme target values.

## Expected output

The final modelling output is a reproducible pipeline and dashboard. The
dashboard will present:

- Predictions for unseen customers in the held-out population.
- Aggregate MAE and RMSE comparisons.
- Per-customer error summaries without publishing raw identifiers.
- Limitations and the synthetic-data disclaimer.

No processed panel or model output is created during Stage 02A.
