# CashFlowAI Parquet Metadata Inventory

This report was generated from Parquet footer metadata and the local HTML data dictionary. It does not contain table records and does not verify data quality or relationships.

## Dataset Summary

| Property | Value |
| --- | ---: |
| Parquet files | 8 |
| Total file size (bytes) | 3,515,988,012 |
| Total metadata rows | 130,614,687 |
| Total row groups | 1,094 |
| PyArrow version | 23.0.1 |

## Table Overview

| Table | Purpose | Rows | Row groups | File size (bytes) |
| --- | --- | ---: | ---: | ---: |
| customers | One row per customer. Contains demographics, segment, language, region, and household information. 221,000 rows. | 200,000 | 2 | 4,227,635 |
| leasing_agreements | Monthly snapshots of leasing and mortgage contracts. Each row represents the state of one agreement at one point in time. 141,967 rows. | 116,660 | 1 | 2,075,564 |
| life_insurance | Monthly snapshots of life insurance policies. 606,089 rows. | 592,381 | 6 | 4,479,430 |
| margin_assets | Monthly balance snapshots for accounts in a positive (asset) position. One row per customer per month where the end balance is positive. 4,591,506 rows. | 4,561,521 | 58 | 112,363,012 |
| margin_liabilities | Monthly balance snapshots for accounts in a negative (liability / overdraft) position. Same structure as margin_assets but for customers who owe money. 714,413 rows. | 238,478 | 4 | 6,016,103 |
| pension | Monthly pension fund contribution records. 2,966,040 rows. | 2,966,040 | 25 | 27,708,082 |
| property_insurance | Monthly snapshots of property (non-life) insurance policies. 1,071,805 rows. | 1,012,945 | 9 | 11,558,891 |
| transactions | Every financial event: card purchases, salaries, transfers, bills, and more. Each row is one transaction. 151.1M rows. | 120,926,662 | 989 | 3,347,559,295 |

## Key and Relationship Candidates

All candidates below are unverified. Footer metadata cannot prove global uniqueness or referential integrity.

| Source | Role | Target | Status |
| --- | --- | --- | --- |
| customers.client_id | unique_identifier_candidate | — | Unverified |
| customers.client_id | join_field_candidate | Not specified | Unverified |
| leasing_agreements.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| life_insurance.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| margin_assets.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| margin_liabilities.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| pension.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| property_insurance.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |
| transactions.txn_id | unique_identifier_candidate | — | Unverified |
| transactions.client_id_fk | foreign_key_candidate | customers.client_id | Unverified |

## Table: `customers`

### Purpose

One row per customer. Contains demographics, segment, language, region, and household information. 221,000 rows.

### Verified Parquet Metadata

- File: `customers.parquet`
- File size: 4,227,635 bytes
- Actual rows: 200,000
- Row groups: 2
- Row-group row-count range: 77,120–122,880
- Column-chunk compressed total: 4,158,700 bytes
- Column-chunk uncompressed total: 7,383,212 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bank_reg_dt | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Date when the customer first registered with the bank. Transactions only exist on or after this date. | 2/2 chunks; min/max 2/2 | 0 | 2010-01-01T00:00:00 — 2025-09-29T00:00:00 |
| birth_or_reg_dt | timestamp[ns] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=nanoseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Date of birth (Private) or company registration date (SME/Corporate). | 2/2 chunks; min/max 2/2 | 0 | 1940-01-01T00:00:00 — 2027-02-10T00:00:00 |
| client_id | string | BYTE_ARRAY | String | True | Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk. | 2/2 chunks; min/max 2/2 | 0 | CL0000001 — CL0200000 |
| corp_group_id | string | BYTE_ARRAY | String | True | Corporate group identifier (only populated for SME/Corporate customers belonging to a group). | 2/2 chunks; min/max 0/2 | 200,000 | Unavailable or incomplete |
| gender_cd | string | BYTE_ARRAY | String | True | Gender. M male. F female. U unknown/undisclosed (business entities). X data anomaly (intentionally injected). | 2/2 chunks; min/max 2/2 | 0 | F — X |
| group_head_flg | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Corporate group head flag. 0 for all private customers. 1 if this company is the head of a corporate group. | 2/2 chunks; min/max 2/2 | 0 | 0 — 0 |
| lang_pref | string | BYTE_ARRAY | String | True | Preferred language. ET Estonian. EN English. RU Russian. | 2/2 chunks; min/max 2/2 | 0 | EN — RU |
| postal_code | string | BYTE_ARRAY | String | True | 5-digit postal code of the customer's registered address. | 2/2 chunks; min/max 2/2 | 0 | 10000 — 94999 |
| segment | string | BYTE_ARRAY | String | True | Customer segment. Private individual retail clients. SME small and medium enterprises. Corporate large corporations. | 2/2 chunks; min/max 2/2 | 0 | Private — Private |
| type_cd | string | BYTE_ARRAY | String | True | Legal entity type. H natural person (human). C legal entity (company). | 2/2 chunks; min/max 2/2 | 0 | C — H |
| household_id | string | BYTE_ARRAY | String | True | Household group identifier. Customers sharing a household_id live together. Singles have a unique ID prefixed S; households use HH. | 2/2 chunks; min/max 2/2 | 0 | HH0000001 — S00199998 |
| household_role | string | BYTE_ARRAY | String | True | Role within household. primary head of household. partner spouse/partner. dependent child or dependent. single lives alone. | 2/2 chunks; min/max 2/2 | 0 | dependent — single |
| region_cd | string | BYTE_ARRAY | String | True | Geographic region. TLN Tallinn. TRT Tartu. NRV Narva. PRN Pärnu. RUR Rural. OTH Other. | 2/2 chunks; min/max 2/2 | 0 | NRV — TRT |

Metadata observations requiring record-level confirmation:

- `group_head_flg`: All reported row-group min/max statistics contain the same non-null value: 0
- `segment`: All reported row-group min/max statistics contain the same non-null value: Private

### Identifiers and Join Fields

- `client_id` — unique_identifier_candidate. Unverified. Evidence: Dictionary description: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.
- `client_id` — join_field_candidate. Unverified. Evidence: Dictionary description: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 221,000
- Actual row count: 200,000
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `group_head_flg`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `cohort_selection_support`
- Assessment: The dictionary describes customer segment information, which would be needed to identify the simulated SME cohort in a later stage.
- Status: `preliminary_unverified`
- Limitations: The distribution and completeness of segment codes require record-level verification.
- Observation: Complete reported row-group min/max statistics identify only the value Private for segment. This may indicate that the extracted customer table contains no SME rows, but Task 2C must verify the segment distribution.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `leasing_agreements`

### Purpose

Monthly snapshots of leasing and mortgage contracts. Each row represents the state of one agreement at one point in time. 141,967 rows.

### Verified Parquet Metadata

- File: `leasing_agreements.parquet`
- File size: 2,075,564 bytes
- Actual rows: 116,660
- Row groups: 1
- Row-group row-count range: 116,660–116,660
- Column-chunk compressed total: 2,008,588 bytes
- Column-chunk uncompressed total: 2,780,185 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| carrying_amount | double | DOUBLE | None | True | Book value of the lease on the bank's balance sheet (EUR). | 1/1 chunks; min/max 1/1 | 0 | 1700.86 — 255224.67 |
| client_id_fk | string | BYTE_ARRAY | String | True | Customer who holds the lease. | 1/1 chunks; min/max 1/1 | 0 | CL0000003 — CL0199968 |
| lease_ccy | string | BYTE_ARRAY | String | True | Currency of the lease contract. EUR USD SEK | 1/1 chunks; min/max 1/1 | 0 | EUR — USD |
| lease_status | string | BYTE_ARRAY | String | True | Current status of the agreement: offer contract proposed but not yet signed. enactment contract signed, disbursement in progress. valid active, payments ongoing. temporary terminated payments paused (e.g. payment holiday). terminated contract ended normally. completely terminated fully settled, no outstanding balance. archived closed and archived. | 1/1 chunks; min/max 1/1 | 0 | archived — valid |
| orig_principal | double | DOUBLE | None | True | Original loan principal at contract signing (EUR). | 1/1 chunks; min/max 1/1 | 0 | 1820.18 — 269015.85 |
| outstanding_principal | double | DOUBLE | None | True | Remaining principal balance as of the snapshot date (EUR). | 1/1 chunks; min/max 1/1 | 0 | 1789.55 — 264628.62 |
| snapshot_date | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Month-end date of this snapshot. | 1/1 chunks; min/max 1/1 | 0 | 2023-12-31T00:00:00 — 2025-12-31T00:00:00 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Snapshot month (partition key). | 1/1 chunks; min/max 1/1 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Snapshot year (partition key). | 1/1 chunks; min/max 1/1 | 0 | 2023 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Customer who holds the lease.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 141,967
- Actual row count: 116,660
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `life_insurance`

### Purpose

Monthly snapshots of life insurance policies. 606,089 rows.

### Verified Parquet Metadata

- File: `life_insurance.parquet`
- File size: 4,479,430 bytes
- Actual rows: 592,381
- Row groups: 6
- Row-group row-count range: 2,919–124,655
- Column-chunk compressed total: 4,128,669 bytes
- Column-chunk uncompressed total: 5,788,300 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| client_id_fk | string | BYTE_ARRAY | String | True | Policyholder. | 6/6 chunks; min/max 6/6 | 0 | CL0000002 — CL0199997 |
| next_premium | double | DOUBLE | None | True | Next premium payment amount (EUR). | 6/6 chunks; min/max 6/6 | 0 | 0.0 — 534.71 |
| policy_ccy | string | BYTE_ARRAY | String | True | Policy currency. EUR USD | 6/6 chunks; min/max 6/6 | 0 | EUR — USD |
| policy_status | string | BYTE_ARRAY | String | True | Estonian regulatory status codes: ALG initial / pending activation. REGTUD registered, active policy. MAKSEOOT premium due / awaiting payment. JOUS in-force, current. KATK suspended (e.g. non-payment). LOPET terminated by policyholder. LOPPKAES terminated by expiry. LOPPSURM terminated by death (claim paid). ANULL annulled / voided. | 6/6 chunks; min/max 6/6 | 0 | ALG — REGTUD |
| snapshot_date | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Month-end date of this snapshot. | 6/6 chunks; min/max 6/6 | 0 | 2023-12-31T00:00:00 — 2025-12-31T00:00:00 |
| sum_insured | double | DOUBLE | None | True | Total insured amount (EUR). | 6/6 chunks; min/max 6/6 | 0 | 6069.11 — 446436.59 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition month. | 6/6 chunks; min/max 6/6 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition year. | 6/6 chunks; min/max 6/6 | 0 | 2023 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Policyholder.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 606,089
- Actual row count: 592,381
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `margin_assets`

### Purpose

Monthly balance snapshots for accounts in a positive (asset) position. One row per customer per month where the end balance is positive. 4,591,506 rows.

### Verified Parquet Metadata

- File: `margin_assets.parquet`
- File size: 112,363,012 bytes
- Actual rows: 4,561,521
- Row groups: 58
- Row-group row-count range: 55,025–118,783
- Column-chunk compressed total: 112,307,253 bytes
- Column-chunk uncompressed total: 170,481,349 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acct_ccy | string | BYTE_ARRAY | String | True | Account currency. EUR USD SEK NOK | 58/58 chunks; min/max 58/58 | 0 | EUR — USD |
| avg_balance_eur | double | DOUBLE | None | True | Average daily balance for the month (EUR). Used for interest calculations. | 58/58 chunks; min/max 58/58 | 0 | 0.0 — 509341.575 |
| avg_interest_base_eur | double | DOUBLE | None | True | Interest-bearing balance after deducting activity penalties (EUR). Reflects the effective base the bank uses for margin calculations. | 58/58 chunks; min/max 58/58 | 0 | 0.0 — 504352.12072223006 |
| client_id_fk | string | BYTE_ARRAY | String | True | Account holder. | 58/58 chunks; min/max 58/58 | 0 | CL0000001 — CL0200000 |
| end_balance_eur | double | DOUBLE | None | True | End-of-month balance (EUR). | 58/58 chunks; min/max 58/58 | 0 | 0.010000000000104592 — 529041.54 |
| month_end | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Last day of the month. | 58/58 chunks; min/max 58/58 | 0 | 2024-01-31T00:00:00 — 2025-12-31T00:00:00 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition month. | 58/58 chunks; min/max 58/58 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition year. | 58/58 chunks; min/max 58/58 | 0 | 2024 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Account holder.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 4,591,506
- Actual row count: 4,561,521
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `margin_liabilities`

### Purpose

Monthly balance snapshots for accounts in a negative (liability / overdraft) position. Same structure as margin_assets but for customers who owe money. 714,413 rows.

### Verified Parquet Metadata

- File: `margin_liabilities.parquet`
- File size: 6,016,103 bytes
- Actual rows: 238,478
- Row groups: 4
- Row-group row-count range: 48,513–63,660
- Column-chunk compressed total: 6,012,015 bytes
- Column-chunk uncompressed total: 8,913,748 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| avg_balance_eur | double | DOUBLE | None | True | Average liability balance for the month (EUR). | 4/4 chunks; min/max 4/4 | 0 | 0.009999999999763531 — 41187.58500000001 |
| avg_interest_base_eur | double | DOUBLE | None | True | Interest-bearing liability base (EUR). | 4/4 chunks; min/max 4/4 | 0 | 0.012356701177905523 — 41697.8232067154 |
| client_id_fk | string | BYTE_ARRAY | String | True | Account holder. | 4/4 chunks; min/max 4/4 | 0 | CL0000003 — CL0199981 |
| contract_ccy | string | BYTE_ARRAY | String | True | Contract currency. EUR USD SEK NOK | 4/4 chunks; min/max 4/4 | 0 | EUR — USD |
| end_balance_eur | double | DOUBLE | None | True | End-of-month outstanding liability (EUR, positive number). | 4/4 chunks; min/max 4/4 | 0 | 9.094947017729282e-13 — 44792.82 |
| month_end | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Last day of the month. | 4/4 chunks; min/max 4/4 | 0 | 2024-01-31T00:00:00 — 2025-12-31T00:00:00 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition month. | 4/4 chunks; min/max 4/4 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition year. | 4/4 chunks; min/max 4/4 | 0 | 2024 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Account holder.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 714,413
- Actual row count: 238,478
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `pension`

### Purpose

Monthly pension fund contribution records. 2,966,040 rows.

### Verified Parquet Metadata

- File: `pension.parquet`
- File size: 27,708,082 bytes
- Actual rows: 2,966,040
- Row groups: 25
- Row-group row-count range: 71,140–124,803
- Column-chunk compressed total: 27,390,036 bytes
- Column-chunk uncompressed total: 53,549,165 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| client_id_fk | string | BYTE_ARRAY | String | True | Account holder. | 25/25 chunks; min/max 25/25 | 0 | CL0000001 — CL0200000 |
| contrib_date | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Contribution month-end date. | 25/25 chunks; min/max 25/25 | 0 | 2023-12-31T00:00:00 — 2025-12-31T00:00:00 |
| contrib_status | string | BYTE_ARRAY | String | True | active regular contributions. stopped contributions suspended. Empty string for initial state. | 25/25 chunks; min/max 0/25 | 0 | Unavailable or incomplete |
| fund_code | string | BYTE_ARRAY | String | True | Selected pension fund: PEN-A conservative (bonds). PEN-B balanced. PEN-C growth (equities). PEN-D aggressive growth. PEN-E index-tracking. | 25/25 chunks; min/max 25/25 | 0 | PEN-A — PEN-E |
| unit_qty | double | DOUBLE | None | True | Cumulative fund units held. | 25/25 chunks; min/max 25/25 | 0 | 0.0 — 107.1164 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition month. | 25/25 chunks; min/max 25/25 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition year. | 25/25 chunks; min/max 25/25 | 0 | 2023 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Account holder.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 2,966,040
- Actual row count: 2,966,040
- Row counts match: True
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `property_insurance`

### Purpose

Monthly snapshots of property (non-life) insurance policies. 1,071,805 rows.

### Verified Parquet Metadata

- File: `property_insurance.parquet`
- File size: 11,558,891 bytes
- Actual rows: 1,012,945
- Row groups: 9
- Row-group row-count range: 23,655–124,446
- Column-chunk compressed total: 11,303,356 bytes
- Column-chunk uncompressed total: 19,537,469 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| agreement_status | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Numeric status: -1 cancelled / surrendered. 0 inactive / pending. 1 active, in force. 2 claim in progress. | 9/9 chunks; min/max 9/9 | 0 | -1 — 2 |
| client_id_fk | string | BYTE_ARRAY | String | True | Policyholder. | 9/9 chunks; min/max 9/9 | 0 | CL0000001 — CL0199999 |
| cover_type_cd | string | BYTE_ARRAY | String | True | Coverage type. E endowment (savings-linked). P pure protection. | 9/9 chunks; min/max 9/9 | 0 | E — P |
| premium_eur | double | DOUBLE | None | True | Monthly premium (EUR). | 9/9 chunks; min/max 9/9 | 0 | 4.74 — 193.14 |
| snapshot_date | timestamp[us] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=microseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Month-end snapshot date. | 9/9 chunks; min/max 9/9 | 0 | 2023-12-31T00:00:00 — 2025-12-31T00:00:00 |
| surrender_value_eur | double | DOUBLE | None | True | Cash surrender value accumulated (EUR). Grows over time for endowment policies. | 9/9 chunks; min/max 9/9 | 0 | 95.69 — 40680.84 |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition month. | 9/9 chunks; min/max 9/9 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Partition year. | 9/9 chunks; min/max 9/9 | 0 | 2023 — 2025 |

### Identifiers and Join Fields

- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Policyholder.; The customers.client_id description identifies it as a join key: Unique customer identifier, e.g. CL0000001. Used as the join key to all other tables via client_id_fk.; The exact client_id_fk column exists in the actual schema.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 1,071,805
- Actual row count: 1,012,945
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: None
- Coarse type-family mismatches:
  - `agreement_status`: dictionary `string` vs Arrow `int64`
  - `month`: dictionary `string` vs Arrow `int64`
  - `year`: dictionary `string` vs Arrow `int64`

### Relevance to SME Cash-Flow Forecasting

- Classification: `contextual_only`
- Assessment: The dictionary describes product or balance snapshots. These may provide contextual features, but this metadata does not establish cash-flow relevance or predictive value.
- Status: `preliminary_unverified`
- Limitations: Snapshot timing, coverage, and alignment with weekly transaction flow require separate validation.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Table: `transactions`

### Purpose

Every financial event: card purchases, salaries, transfers, bills, and more. Each row is one transaction. 151.1M rows.

### Verified Parquet Metadata

- File: `transactions.parquet`
- File size: 3,347,559,295 bytes
- Actual rows: 120,926,662
- Row groups: 989
- Row-group row-count range: 53,263–124,902
- Column-chunk compressed total: 3,274,664,024 bytes
- Column-chunk uncompressed total: 8,026,689,604 bytes
- Parquet writer: DuckDB version v1.4.4 (build 6ddac802ff)
- Parquet format version: 1.0

### Column Inventory

| Column | Arrow type | Parquet physical type | Logical type | Nullable | Dictionary description | Statistics | Null count (metadata) | Metadata min–max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acct_iban | string | BYTE_ARRAY | String | True | IBAN of the account being debited or credited. | 989/989 chunks; min/max 989/989 | 0 | EE010000000001000069 — EE970000000002199475 |
| amount_eur | double | DOUBLE | None | True | Amount converted to EUR at the applicable exchange rate. | 989/989 chunks; min/max 989/989 | 0 | 0.05 — 80425.58 |
| amount_orig | double | DOUBLE | None | True | Transaction amount in the original currency (trx_ccy). | 989/989 chunks; min/max 989/989 | 0 | 0.6 — 80425.58 |
| book_date | timestamp[ns] | INT64 | Timestamp(isAdjustedToUTC=false, timeUnit=nanoseconds, is_from_converted_type=false, force_set_converted_type=false) | True | Date the transaction was booked. | 989/989 chunks; min/max 989/989 | 0 | 2024-01-01T00:00:00 — 2025-12-31T00:00:00 |
| book_time | string | BYTE_ARRAY | String | True | Time of day in HH:MM:SS format. | 989/989 chunks; min/max 989/989 | 0 | 00:00:00 — 23:59:59 |
| channel | string | BYTE_ARRAY | String | True | Channel used. card POS / contactless terminal. online internet banking. mobile mobile app. branch physical branch visit. atm ATM machine. | 989/989 chunks; min/max 989/989 | 0 | atm — online |
| client_id_fk | string | BYTE_ARRAY | String | True | Customer who owns the account. Joins to customers.client_id. | 989/989 chunks; min/max 989/989 | 0 | CL0000001 — CL0200000 |
| counterparty_iban | string | BYTE_ARRAY | String | True | IBAN of the other party (employer, merchant, transfer recipient, etc.). | 989/989 chunks; min/max 989/989 | 194,178 | EE004455445544554455 — XX99999250055562637 |
| day_in_month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | Day of the month (1–31). | 989/989 chunks; min/max 989/989 | 0 | 1 — 31 |
| dc_indicator | string | BYTE_ARRAY | String | True | Direction. C credit (money in). D debit (money out). | 989/989 chunks; min/max 989/989 | 0 | C — D |
| mcc | string | BYTE_ARRAY | String | True | Merchant Category Code (ISO 18245). Present on card purchases and subscriptions; null for transfers and salary. Examples: 5411 grocery, 5812 restaurants, 6011 ATM. | 989/989 chunks; min/max 979/989 | 24,375,547 | Unavailable or incomplete |
| merchant_country | string | BYTE_ARRAY | String | True | ISO 2-letter country code of the merchant. Most are EE; cross-border transactions show the merchant's actual country. | 989/989 chunks; min/max 979/989 | 24,375,547 | Unavailable or incomplete |
| period_yy_mm | string | BYTE_ARRAY | String | True | Year-month period, e.g. 2401 for January 2024. Useful for grouping. | 989/989 chunks; min/max 989/989 | 0 | 2401 — 2512 |
| trx_ccy | string | BYTE_ARRAY | String | True | Original currency. EUR USD SEK NOK GBP | 989/989 chunks; min/max 989/989 | 0 | EUR — USD |
| txn_id | string | BYTE_ARRAY | String | True | Unique transaction identifier, e.g. TX00000000001. | 989/989 chunks; min/max 989/989 | 0 | TX00000000001 — TX00151107982 |
| txn_type | string | BYTE_ARRAY | String | True | Transaction classification (see table below). | 989/989 chunks; min/max 989/989 | 0 | allowance_transfer — utility_bill |
| purpose_code | string | BYTE_ARRAY | String | True | SEPA purpose code (see table below). | 989/989 chunks; min/max 989/989 | 0 | BENE — SUPP |
| weekday_name | string | BYTE_ARRAY | String | True | Abbreviated weekday: Mon, Tue, ..., Sun. | 989/989 chunks; min/max 989/989 | 0 | Fri — Wed |
| month | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | — | 989/989 chunks; min/max 989/989 | 0 | 1 — 12 |
| year | int64 | INT64 | Int(bitWidth=64, isSigned=true) | True | — | 989/989 chunks; min/max 989/989 | 0 | 2024 — 2025 |

### Identifiers and Join Fields

- `txn_id` — unique_identifier_candidate. Unverified. Evidence: Dictionary description: Unique transaction identifier, e.g. TX00000000001.
- `client_id_fk` — foreign_key_candidate → customers.client_id. Unverified. Evidence: Dictionary description: Customer who owns the account. Joins to customers.client_id.

### Schema and Dictionary Reconciliation

- Dictionary table matched: True
- Dictionary row count: 151,100,000
- Actual row count: 120,926,662
- Row counts match: False
- Documented fields absent from schema: None
- Schema fields absent from dictionary: `month`, `year`
- Coarse type-family mismatches: None

### Relevance to SME Cash-Flow Forecasting

- Classification: `direct_candidate`
- Assessment: The dictionary describes individual financial events, and the actual footer schema contains fields plausibly relevant to weekly bank-transaction cash flow.
- Status: `preliminary_unverified`
- Limitations: Field presence does not establish data quality, sign semantics, SME coverage, or weekly completeness.

### Record-Level Verification Required

- Statistics cannot prove global uniqueness or foreign-key validity.
- Null counts and min/max values are reported only where the Parquet footer provides them.
- Value domains, temporal continuity, SME eligibility and cash-flow semantics require Task 2C profiling.
- Data-dictionary claims remain distinct from verified Parquet metadata.

## Global Limitations

- No Parquet table, row group, or column values were loaded.
- SME eligibility, uniqueness, joins, temporal continuity and cash-flow semantics remain unverified.
- Record-level profiling must be a separate Task 2C activity.

Detailed row-group and column-chunk metadata is retained in `parquet_inventory.json`.
