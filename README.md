# CashFlowAI: Machine Learning for Personal Cash-Flow Forecasting

This repository develops a reproducible prototype for forecasting next-week
net bank-transaction cash flow for individual banking customers. The project
was migrated from an SME focus after record-level analysis found no
authoritatively labelled SME customers in the available dataset.

## Current research question

> How accurately can machine-learning models forecast the next week's net
> bank-transaction cash flow for individual banking customers compared with
> simple forecasting methods?

The scope decision, methodology, roadmap and academic-approval status are
documented in [the scope change decision](docs/project_management/scope_change_decision.md).
The original proposal, weekly plan and SME-focused inspection reports are
retained as historical evidence and are not current project specifications.

## Scope

The source archive is `synthetic_banking.tar.gz`. It is an immutable local
input and must not be committed, re-extracted, uploaded, or modified. A
read-only local extraction exists under `synthetic_banking/`; that directory
is ignored by Git.

The current analytical scope is personal bank-transaction cash flow:

- Eligible records are Private customers only.
- The target is next-week net cash flow in EUR, defined as credits minus
  debits.
- At most five eligible customers will be selected using criteria frozen
  before selection.
- The same preprocessing, feature engineering, temporal evaluation and model
  comparison rules will be applied to every selected customer.
- The study is an educational forecasting prototype, not full accounting cash
  flow, live banking, lending or customer-profiling software.

The `data/raw`, `data/interim`, and `data/processed` directories contain only
tracked `.gitkeep` placeholders at this stage. Generated reports should be
deterministic, sanitised, and appropriate for a public academic portfolio.
Small documentation and inspection reports may be committed. Raw data,
archives, Parquet files, and large generated data artefacts are ignored.

## Environment setup (Windows PowerShell)

The existing `.venv` is preserved. This project was checked with Python
3.14.9 on Windows. The pinned packages resolve to a native CPython 3.14 wheel
for PyArrow and a universal pytest wheel.

```powershell
# Create a new environment only when one is needed; do not recreate an existing .venv.
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If Python 3.14 is unavailable on another machine, Python 3.12 is the
documented fallback:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

## Verification

Run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Task 1 tests verify only the required directory layout and configuration
files. They do not inspect, extract, or make claims about the history of the
dataset archive.

## Archive inventory

Generate a deterministic, metadata-only inventory without extracting any
archive member:

```powershell
.\.venv\Scripts\python.exe -B scripts\inspect_archive.py `
    synthetic_banking.tar.gz `
    --report reports\data_inspection\archive_inventory.md
```

The command reads archive headers only, reports member paths, sizes, types and
safety warnings, and records the location of `DATA_DICTIONARY.html`. It does
not read Parquet records, parse the dictionary, or inspect table schemas.

## Parquet metadata inventory

Inspect all extracted Parquet footers and reconcile their schemas with the
local data dictionary:

```powershell
.\.venv\Scripts\python.exe -B scripts\inspect_parquet_metadata.py
```

The command writes detailed JSON metadata and a review-oriented Markdown report
under `reports/data_inspection/`, together with a compact structured JSON
summary. The full technical JSON remains local because its exhaustive
row-group statistics make it unsuitable for a normal source commit. It does
not load tables or row groups, use pandas, or scan transaction records.

## Historical SME feasibility check

This retained script and reports document why the project moved to a personal
scope:

```powershell
.\.venv\Scripts\python.exe -B scripts\check_sme_feasibility.py
```

The script scans only the required customer columns. It scans transaction
columns in bounded batches only when identifiable SME-labeled customers exist.
Reports contain aggregate values only and no customer identifiers or
transaction records.

## Comprehensive aggregate profiling

Run the bounded record-level profile across all eight tables:

```powershell
.\.venv\Scripts\python.exe -B scripts\profile_dataset_comprehensive.py
```

The profiler makes one coordinated pass over `transactions.parquet`, scans the
other tables in bounded batches, and retains only aggregate state. It does not
load complete tables, publish raw identifiers, or modify source data.

The completed evidence is available in
[the comprehensive dataset analysis](reports/data_inspection/comprehensive_dataset_analysis.md).

## Dependencies

- `pyarrow==23.0.1` — used for bounded Parquet metadata and record-level
  aggregate inspection.
- `pytest==9.0.2` — development test runner.

DuckDB is intentionally not included: the current inspection workflows use
PyArrow and do not require it.
