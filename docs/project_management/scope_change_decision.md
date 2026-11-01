# CashFlowAI Scope Change Decision

## Decision status

This document records the team's repository-level decision to change the active
project scope from small-business cash-flow forecasting to personal
bank-transaction cash-flow forecasting.

The migration is a project decision, not evidence of academic approval. The
existing proposal and weekly-plan documents remain historical. Any module or
assessment approval process required after a scope change must still be
completed by the team.

## Title and research question

### Previous title

CashFlowAI: Machine Learning for Small Business Cash-Flow Forecasting

### Current title

CashFlowAI: Machine Learning for Personal Cash-Flow Forecasting

### Original research question

How accurately can machine-learning models forecast the next week's net
bank-transaction cash flow for simulated small businesses compared with simple
forecasting methods?

### Current research question

How accurately can machine-learning models forecast the next week's net
bank-transaction cash flow for individual banking customers compared with
simple forecasting methods?

The target remains next-week net bank-transaction cash flow, not full accounting
cash flow. It is calculated from bank transaction credits minus debits in EUR.

## Why the scope changed

The comprehensive record-level analysis established the following evidence:

- `customers.parquet` contains exactly 200,000 customers.
- Every customer has the segment value `Private`.
- There are zero SME-labelled and zero Corporate-labelled customer rows.
- Customer identifiers are non-null and unique across those 200,000 rows.
- All customer references in transactions and every product/balance table
  match the available customer table.
- No table contains an alternative authoritative SME or business
  classification.
- The data dictionary claims 20,000 SME and 1,000 Corporate customers, but
  those populations are absent from the supplied export.
- Transaction row counts and several product-table row counts also differ from
  their dictionary claims, indicating that the export is not the full
  population described by the dictionary.

The absence of SME records cannot be repaired through joining because there
are no orphan customer identifiers that could expose a hidden SME population.
Transaction amounts, product ownership, legal-entity codes and identifier
patterns are not authoritative segment labels and must not be used to relabel
Private customers.

The supporting evidence is preserved in:

- [SME feasibility report](../../reports/data_inspection/sme_feasibility.md)
- [SME feasibility summary](../../reports/data_inspection/sme_feasibility.json)
- [Comprehensive dataset analysis](../../reports/data_inspection/comprehensive_dataset_analysis.md)
- [Comprehensive structured findings](../../reports/data_inspection/comprehensive_dataset_analysis.json)

## Why the dataset supports personal cash-flow forecasting

The dataset provides a defensible basis for the revised scope:

- The customer table contains 200,000 non-null, unique Private customer
  identifiers.
- `transactions.parquet` contains 120,926,662 financial events.
- The transaction schema contains the required customer reference, booking
  date, EUR amount and credit/debit direction.
- Transaction dates cover 731 distinct days from 2024-01-01 through
  2025-12-31.
- Transaction customer references have complete overlap with the customer
  table: 120,926,662 matching rows, zero null references and zero orphans.
- Core transaction fields are complete: `amount_eur` contains no nulls, zeros
  or negative amounts, while `book_date` and `dc_indicator` contain no nulls.

These facts support forecasting individual customers' bank-transaction cash
flow, subject to eligibility, history-length and data-quality checks.

## Revised methodology

The core forecasting design is retained:

1. Select no more than five eligible Private customers using criteria frozen
   before selection.
2. Require an exact `segment` value of `Private`, a valid customer identifier,
   complete core transaction fields and enough observed history to support
   time-based evaluation.
3. Calculate weekly net cash flow as EUR credits minus EUR debits:

   `net_cash_flow_week = sum(amount_eur where dc_indicator = C)
   - sum(amount_eur where dc_indicator = D)`

4. Use at least two simple forecasting baselines.
5. Evaluate at least one machine-learning algorithm against those baselines.
6. Use chronological, rolling-origin evaluation with past-only features.
7. Report MAE and RMSE.
8. Apply identical preprocessing, feature engineering and evaluation rules to
   every selected customer.
9. Preserve reproducibility tests, documented limitations and the academic
   portfolio dashboard.

No customer has been selected, no weekly series has been aggregated, and no
model or dashboard feature is implemented by this scope-change task.

### Eligibility criteria to freeze before selection

The selection protocol must document and freeze:

- Exact Private segment status.
- Valid and non-null customer linkage.
- Weekly coverage and minimum observed history.
- Treatment of weeks with no transactions.
- Minimum transaction activity needed for a stable forecast evaluation.
- A deterministic tie-break if more than five customers satisfy the criteria.

The numerical history and activity thresholds require the forthcoming weekly
coverage analysis. They must be fixed before customer selection to avoid
selecting customers because their eventual forecast results look favourable.

## Evaluation and leakage controls

- All features at forecast origin must use information available before the
  target week.
- Train, validation and test periods must follow chronological boundaries.
- Scaling, feature selection and model selection must be fitted within each
  training window only.
- Baselines and machine-learning models must use the same target definition,
  evaluation periods and metric calculation.
- Per-customer results and common aggregate results must both be reported.
- Missing weeks and zero-flow weeks must be handled by a documented rule rather
  than dropped inconsistently.
- Results on synthetic banking data must not be presented as evidence of
  real-world personal financial forecasting performance.

## Reused project components

The migration preserves:

- The `cashflowai` package and existing folder architecture.
- Archive inventory and integrity controls.
- Parquet metadata inspection scripts and reports.
- SME feasibility analysis as historical decision evidence.
- Comprehensive eight-table profiling and relationship verification.
- Existing tests, deterministic reporting conventions and README verification
  commands.
- The local PyArrow/pytest environment and pinned dependencies.
- Git history and the existing remote repository.

## Deliverables and milestones

The deliverables remain technical documentation, a public project portfolio,
an evaluated forecasting prototype, a simple dashboard and the final
presentation/viva. Week numbers follow the existing project schedule; no
calendar dates are invented here.

| Week | Current-scope milestone | Primary responsibility | Exit condition |
| ---: | --- | --- | --- |
| 2 | Confirm revised scope and dataset readiness | All; Mert leads data evidence | Scope record reviewed; dataset limitations and SME evidence preserved |
| 3 | Freeze Private-customer eligibility and build reproducible transaction preparation | Mert, with Rahul review | Documented selection criteria; versioned cleaning and weekly aggregation scripts |
| 4 | Explore personal weekly series and freeze target/splits | Mert and Rahul; Mekha reviews | Eligible series, missing-week rule, temporal split specification |
| 5 | Implement at least two simple baselines and past-only features | Rahul, with Mert review | Reproducible baseline results and feature specification |
| 6 | Train at least one candidate machine-learning model | Rahul, with Mert and Mekha review | Reproducible model comparison draft without leakage |
| 7 | Run rolling-origin evaluation and begin dashboard integration | Rahul and Mekha | MAE/RMSE results and first integrated forecast view |
| 8 | Finalize model comparison and test integrated prototype | Rahul and Mekha | Evaluation report, limitations and working demo |
| 9 | Finalize portfolio, tests and presentation evidence | Mekha and all | Public repository and reproducible artefacts |
| 10 | Verification and portfolio buffer | All | Independent rerun and review findings addressed |
| 11 | Reflection and viva preparation | All | Individual reflections and group rehearsal complete |

## Team responsibility changes

- Mert Pehlivan continues to lead data engineering and quality. The work changes
  from SME selection to Private-customer eligibility, reproducible extraction,
  weekly aggregation and data-quality controls.
- Rahul Ravi continues to lead forecasting and evaluation. The work changes
  from per-SME forecasting to per-customer personal cash-flow forecasting while
  retaining baselines, machine learning, rolling-origin validation and
  MAE/RMSE.
- Mekha Molly Raju continues to lead dashboard, integration and portfolio. The
  interface and reports must identify customers using non-sensitive labels or
  customer codes, not expose raw identifiers, and communicate synthetic-data
  limitations.
- All members remain jointly responsible for methodology review, ethics,
  limitations, task-board updates and contribution evidence.

## Historical versus current documents

The following are historical evidence and must remain unedited:

- `CashFlowAI_Final_Project_Proposal.docx`
- `CashFlowAI_Final_Project_Proposal.pdf`
- `CashFlowAI_Task_Division_Weekly_Plan.docx`
- Existing Task 2A, Task 2B, Task 2C-1 and comprehensive analysis reports
- Existing inspection scripts whose names, comments and outputs preserve the
  original SME investigation

This decision document and the README are the current scope references. A
historical report may describe SME feasibility or SME relevance because it
records the evidence available before the migration.

## Known limitations

- The dataset is synthetic and covers a short historical window.
- The target is bank-transaction cash flow, not a complete accounting view.
- Some customers may have sparse or irregular weekly activity.
- The existing export is a partial population relative to the data dictionary.
- Transaction account identifiers have no supplied account dimension.
- Customer dates contain known inconsistencies, and transaction context fields
  contain missing values.
- The existing Git remote repository name retains the earlier small-business
  title because renaming remote settings is outside this task.
- The original proposal and weekly plan still carry the old scope until any
  formally required replacement documents are prepared and approved.

## Academic approval and resubmission

No tutor or module-leader approval of this revised scope is asserted by this
repository migration.

The team must confirm with the module leader whether the revised title and
research question require:

- A formal proposal amendment or resubmission.
- Updated assessment-declaration text.
- A new project-board or portfolio notice.
- Reapproval before forecasting implementation begins.

The effective rule is that repository work follows the revised scope, while
the academic record must not be represented as approved until the team obtains
and records that approval.

## Change control

Future analytics should use the current title and research question. Historical
files should not be rewritten to match the new wording. If the scope changes
again, create another decision record rather than deleting this one.
