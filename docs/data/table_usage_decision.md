# Table Usage Decision

## Decision status

This document is the current source-table decision for the CashFlowAI personal
cash-flow forecasting project. It is based on the accepted comprehensive
dataset analysis and the customer-distribution analysis.

Only two tables are required for the initial modelling dataset:

| Table | Rows | Referenced customers | Final role |
| --- | ---: | ---: | --- |
| `customers` | 200,000 | 200,000 | Required: eligibility and deterministic customer partitioning |
| `transactions` | 120,926,662 | 200,000 | Required: weekly target and transaction-history features |

The remaining tables are not included in the initial pipeline. They cannot be
joined directly to raw transactions because each has many rows per customer
and would multiply transaction-level rows.

## Evidence common to all tables

- `customers.client_id` is non-null and unique; it is the verified customer key.
- All non-customer tables use `client_id_fk`.
- Every non-null `client_id_fk` value matched the 200,000-row customer table.
- There were no orphan customer references in any table.
- All tables are one-to-many from the customer perspective.
- Product and balance tables are not keyed by agreement, policy or account in
  their schemas. Their relationship to a contract can therefore not be
  reconstructed uniquely from the supplied fields.
- Product and balance values require as-of handling. A record carrying a
  month-end date is not assumed to have been available before that date.

## Detailed decisions

### `customers.parquet`

- **Role:** Required.
- **Rows and key:** 200,000 rows; `client_id` is verified unique and non-null.
- **Coverage:** 200,000 customers.
- **Relevant fields:** `client_id`, `segment`, `bank_reg_dt`, `type_cd`.
- **Granularity:** One static master row per customer.
- **Quality:** All rows have `segment = Private`; `corp_group_id` is null for
  every customer; 404 records have `birth_or_reg_dt` after `bank_reg_dt`.
- **Historical availability:** Stable customer attributes can be used for
  grouping or eligibility only. The file does not prove the historical value
  or availability date of mutable attributes.
- **Leakage risk:** Low for immutable identifiers and the current eligibility
  label; unknown for potentially mutable demographics.
- **Join risk:** One-to-one on `client_id`; no row multiplication.
- **Decision:** Use only the exact Private eligibility flag and customer
  identifier for partitioning. Do not use demographics, legal-entity code or
  missing corporate-group fields as initial features.

### `transactions.parquet`

- **Role:** Required.
- **Rows and key:** 120,926,662 rows; `client_id_fk` provides the verified
  customer relation. `txn_id` remains a candidate identifier because exact
  global uniqueness was not established.
- **Coverage:** All 200,000 customers; zero null or orphan customer references.
- **Relevant fields:** `client_id_fk`, `book_date`, `amount_eur`,
  `dc_indicator`.
- **Date granularity:** Individual booked transactions across 731 days from
  2024-01-01 through 2025-12-31.
- **Quality:** Core target fields are complete, with no zero or negative
  `amount_eur` values. `mcc` and `merchant_country` are each 20.157% null;
  `counterparty_iban` is 0.161% null. There are 305,471 EUR-denominated
  transactions whose original and converted amounts differ, and unresolved
  transaction-ID duplicate risk.
- **Historical availability:** A transaction becomes usable only after its
  booked week is complete.
- **Leakage risk:** High if any record from the target week or later enters a
  feature. Feature construction must lag the target week.
- **Join risk:** Customer joins are one-to-many. No product join may be applied
  directly at transaction granularity.
- **Decision:** Use `dc_indicator`, `book_date` and `amount_eur` to construct
  weekly credits, debits and net flow. Use `client_id_fk` only for panel
  linkage and partitioning.

### `margin_assets.parquet`

- **Role:** Optional validated feature source; excluded from the initial model.
- **Rows and coverage:** 4,561,521 rows covering 199,734 customers.
- **Granularity:** Monthly positive-balance snapshots keyed only by customer
  and month-end date in the available schema.
- **Quality:** No nulls in profiled fields. Composite-key exactness was deferred
  because of cardinality.
- **Historical availability:** The source does not document a publication lag
  or whether the month-end value was known at every intra-month forecast origin.
- **Leakage risk:** High if a month-end snapshot is used for an earlier week.
- **Join risk:** Multiple rows per customer can multiply transaction records.
- **Decision:** Exclude initially. Reconsider only after an as-of rule, lag and
  customer-month aggregation are validated.

### `margin_liabilities.parquet`

- **Role:** Optional validated feature source; excluded from the initial model.
- **Rows and coverage:** 238,478 rows covering 37,234 customers.
- **Granularity:** Monthly liability snapshots with one observed row per
  customer/month for the available keys.
- **Quality:** No nulls in profiled fields.
- **Historical availability:** No source metadata establishes publication time
  or a safe lag before an intra-month forecast.
- **Leakage risk:** High without a conservative availability delay.
- **Join risk:** Multiple rows per customer can multiply transactions.
- **Decision:** Exclude initially. It cannot be used as evidence of a negative
  transaction cash-flow week or insufficient balance without separate temporal
  validation.

### `leasing_agreements.parquet`

- **Role:** Excluded from the initial model.
- **Rows and coverage:** 116,660 rows covering 17,898 customers.
- **Granularity:** Monthly agreement snapshots; no agreement identifier is
  available to distinguish multiple contracts.
- **Quality:** No nulls in profiled fields. `(client_id_fk, snapshot_date)` was
  unique in the observed file, but this does not identify a real-world contract.
- **Historical availability:** Agreement state may become known at different
  points within a month; the file does not prove when each snapshot was
  available.
- **Leakage risk:** High without an explicit reporting lag.
- **Join risk:** Multiple snapshots per customer.
- **Decision:** Exclude. Reconsider only with a documented historical
  availability rule and customer-month aggregation.

### `life_insurance.parquet`

- **Role:** Excluded from the initial model.
- **Rows and coverage:** 592,381 rows covering 43,994 customers.
- **Granularity:** Monthly policy snapshots without a policy identifier.
- **Quality:** No nulls in profiled fields. Three duplicate
  `(client_id_fk, snapshot_date)` combinations were observed.
- **Historical availability:** The available schema does not establish when
  status or premium snapshots became known.
- **Leakage risk:** High if current status is projected backwards.
- **Join risk:** Multiple policies and snapshots per customer.
- **Decision:** Exclude from the initial model.

### `property_insurance.parquet`

- **Role:** Excluded from the initial model.
- **Rows and coverage:** 1,012,945 rows covering 69,886 customers.
- **Granularity:** Monthly property-insurance snapshots without a policy
  identifier.
- **Quality:** No nulls in profiled fields. Exact customer/month uniqueness was
  deferred because of cardinality.
- **Historical availability:** Publication timing is undocumented.
- **Leakage risk:** High without a validated as-of lag.
- **Join risk:** Multiple snapshots per customer.
- **Decision:** Exclude from the initial model.

### `pension.parquet`

- **Role:** Excluded from the initial model.
- **Rows and coverage:** 2,966,040 rows covering 123,585 customers.
- **Granularity:** Monthly contribution snapshots without a fund-account
  identifier.
- **Quality:** No nulls in profiled fields. Exact customer/month uniqueness was
  deferred.
- **Historical availability:** The availability date of contribution records is
  not documented.
- **Leakage risk:** High if future contributions or period-end states are used
  at an earlier origin.
- **Join risk:** Multiple contribution records per customer and month.
- **Decision:** Exclude from the initial model.

## Join and row-multiplication rules

- Join product and balance tables only after aggregating to a documented
  customer-period grain.
- Treat month-end values as available only after applying an explicit,
  evidence-based lag.
- Never attach a monthly snapshot to every transaction in that month without
  validating whether the snapshot was known at each forecast origin.
- Do not treat a customer's current product ownership as historical ownership.
- Do not use a shared customer identifier as proof that an agreement, policy or
  balance table can be safely joined.

## Final initial-pipeline decision

The initial reproducible pipeline uses only:

1. `customers.parquet` for the Private population and customer-level partition
   keys.
2. `transactions.parquet` for weekly credits, debits, net cash flow and
   historical activity features.

The remaining six tables remain available for later, separately reviewed
contextual analyses but are not required to construct or evaluate the initial
forecasting dataset.
