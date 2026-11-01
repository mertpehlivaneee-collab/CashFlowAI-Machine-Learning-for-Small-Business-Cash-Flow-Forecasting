# CashFlowAI

Stage 01 establishes a reproducible, read-only foundation for inspecting the
synthetic banking dataset. This task deliberately includes no data extraction,
sampling, transformation, schema assumptions, or forecasting.

## Scope

The source archive is `synthetic_banking.tar.gz`. It is an immutable local
input and must not be committed, re-extracted, uploaded, or modified. A
read-only local extraction exists under `synthetic_banking/`; that directory
is ignored by Git. Task 2A adds archive inventory, and later tasks will add
metadata-only Parquet inspection without loading complete files into pandas.

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

## SME feasibility check

Run the focused customer-segment and conditional transaction-linkage check:

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

## Dependencies

- `pyarrow==23.0.1` — planned for read-only Parquet metadata inspection in a
  later task.
- `pytest==9.0.2` — development test runner.

DuckDB is intentionally not included yet: Task 1 has no inspection scripts
requiring it. It may be evaluated in a later task if it materially simplifies
read-only metadata inspection.
