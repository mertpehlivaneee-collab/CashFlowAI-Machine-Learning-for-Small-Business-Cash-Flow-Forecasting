# CashFlowAI SME Feasibility Verification

## Material Finding

No identifiable SME customers were found. The extracted customers table contains only `Private` segment labels, so SME selection and transaction linkage are not feasible with this file.

## Verified Findings

| Measure | Verified value |
| --- | ---: |
| Customer rows scanned | 200,000 |
| Segment values and counts | Private: 200,000 |
| Null segment labels | 0 |
| SME-labelled rows | 0 |
| Unique SME identifiers | 0 |
| Null customer identifiers | 0 |
| Blank customer identifiers | 0 |
| Unique non-null customer identifiers | 200,000 |
| Duplicate identifier rows | 0 |
| Identifier uniqueness confirmed | True |

These values are direct aggregates from the selected `client_id` and `segment` columns.

## Data Dictionary Claims

Dictionary values below are claims from `DATA_DICTIONARY.html` and are not record-verified findings.

- Documented customer rows: 221,000
- Documented segment labels: Private, SME, Corporate
- Documented segment counts: Private: 200,000; SME: 20,000; Corporate: 1,000

## Segment Reconciliation

- All observed values documented: True
- All documented values observed: False
- Unexpected observed values: None
- Missing documented values: ['Corporate', 'SME']
- Segment counts match: False
- Customer count matches: False

## Transaction Linkage Feasibility

- Status: `not_tested_no_identifiable_sme_customers`
- Transactions file opened: False
- Reason: No row in customers.parquet has an exact segment label of SME, so there is no defensible SME identifier set for a transaction filter.
- The complete transactions file was not scanned.

## Smallest Next Diagnostic

Confirm the dataset export version and completeness with the source provider. Customers.parquet contains 200,000 Private customers but no documented SME or Corporate labels. Scanning transactions cannot recover a missing customer segment label.

## Scope and Limitations

- Only customer identifier and segment columns were scanned for the customer feasibility result.
- Dictionary claims are kept separate from verified record aggregates.
- No SME selection, cleaning, aggregation, feature engineering, model training, or transaction export was performed.
- Transactions were not opened because no identifiable SME customer was found.

The report contains aggregate values only. Customer identifiers and transaction records are not published.
