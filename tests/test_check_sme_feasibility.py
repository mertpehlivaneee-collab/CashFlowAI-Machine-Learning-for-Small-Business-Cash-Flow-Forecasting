"""Tests for focused SME feasibility verification."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import check_sme_feasibility
from scripts import inspect_parquet_metadata


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_sme_feasibility.py"


def write_dictionary(path: Path, expected_sme: int) -> None:
    path.write_text(
        f"""
<!doctype html>
<html><body>
<h3>Customer Segments</h3>
<p>Private 3 SME {expected_sme} Corporate 0</p>
<h2 id="customers">customers</h2>
<p>One row per customer. 5 rows.</p>
<table>
  <tr><th>Column</th><th>Type</th><th>Description</th></tr>
  <tr><td>client_id</td><td>string</td>
      <td>Unique customer identifier. Used as a join key.</td></tr>
  <tr><td>segment</td><td>string</td>
      <td>Customer segment including Private, SME and Corporate.</td></tr>
</table>
<h2 id="transactions">transactions</h2>
<p>Every financial event. 4 rows.</p>
<table>
  <tr><th>Column</th><th>Type</th><th>Description</th></tr>
  <tr><td>txn_id</td><td>string</td>
      <td>Unique transaction identifier.</td></tr>
  <tr><td>client_id_fk</td><td>string</td>
      <td>Customer reference. Joins to customers.client_id.</td></tr>
  <tr><td>book_date</td><td>date</td>
      <td>The date the transaction was booked.</td></tr>
  <tr><td>amount_eur</td><td>float</td>
      <td>Amount converted to EUR.</td></tr>
  <tr><td>dc_indicator</td><td>string</td>
      <td>Direction. C credit and D debit.</td></tr>
</table>
</body></html>
        """.strip(),
        encoding="utf-8",
    )


def write_customers(
    path: Path,
    identifiers: list[str | None],
    segments: list[str | None],
) -> None:
    table = pa.table({"client_id": identifiers, "segment": segments})
    pq.write_table(table, path, row_group_size=2)


def write_transactions(path: Path) -> None:
    table = pa.table(
        {
            "txn_id": ["T1", "T2", "T3"],
            "client_id_fk": ["C1", "C1", "C2"],
            "book_date": [
                pa.scalar("2024-01-01").cast(pa.timestamp("ns")),
                pa.scalar("2024-01-08").cast(pa.timestamp("ns")),
                None,
            ],
            "amount_eur": [10.0, 20.0, None],
            "dc_indicator": ["C", "D", None],
        }
    )
    pq.write_table(table, path, row_group_size=2)


def write_metadata_report(
    dataset: Path, dictionary: Path, report_path: Path
) -> None:
    report = inspect_parquet_metadata.inspect_dataset(dataset, dictionary)
    compact = inspect_parquet_metadata.summarise_report(report)
    report_path.write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_dataset(
    tmp_path: Path,
    *,
    include_sme: bool,
) -> tuple[Path, Path, Path]:
    dataset = tmp_path / "student_export"
    dataset.mkdir()
    dictionary = dataset / "DATA_DICTIONARY.html"
    metadata_path = tmp_path / "metadata.json"
    write_dictionary(dictionary, expected_sme=1 if include_sme else 0)
    if include_sme:
        write_customers(
            dataset / "customers.parquet",
            ["C1", "C2", "C3"],
            ["SME", "Private", None],
        )
    else:
        write_customers(
            dataset / "customers.parquet",
            ["C1", "C2", "C3"],
            ["Private", "Private", "Private"],
        )
    write_transactions(dataset / "transactions.parquet")
    write_metadata_report(dataset, dictionary, metadata_path)
    return dataset, dictionary, metadata_path


def test_customer_scan_counts_nulls_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "customers.parquet"
    write_customers(
        path,
        ["C1", "C1", None, ""],
        ["SME", "SME", "Private", None],
    )

    result = check_sme_feasibility.scan_customers(
        path, "client_id", "segment", batch_size=2
    )

    assert result["actual_customer_count"] == 4
    assert result["identifier_null_count"] == 1
    assert result["identifier_blank_count"] == 1
    assert result["identifier_unique_non_null_count"] == 2
    assert result["identifier_duplicate_row_count"] == 1
    assert result["identifier_is_unique"] is False
    assert result["sme_labelled_customer_rows"] == 2
    assert result["sme_unique_identifier_count"] == 1
    assert result["null_segment_count"] == 1
    assert result["_sme_identifiers"] == {"C1"}


def test_no_sme_stops_before_transactions_are_opened(tmp_path: Path) -> None:
    dataset, dictionary, metadata_path = prepare_dataset(
        tmp_path, include_sme=False
    )
    transactions_path = dataset / "transactions.parquet"
    transactions_path.unlink()

    report = check_sme_feasibility.build_feasibility_report(
        dataset, metadata_path, dictionary
    )

    assert report["conclusion"]["identifiable_sme_customers_found"] is False
    assert report["verified_findings"]["sme_labelled_customer_rows"] == 0
    assert report["transaction_feasibility"]["transaction_file_opened"] is False
    assert (
        report["transaction_feasibility"]["status"]
        == "not_tested_no_identifiable_sme_customers"
    )
    assert report["customer_segment_reconciliation"][
        "all_observed_values_documented"
    ]
    assert report["customer_segment_reconciliation"][
        "all_documented_values_observed"
    ] is False


def test_sme_branch_checks_linkage_and_completeness(tmp_path: Path) -> None:
    dataset, dictionary, metadata_path = prepare_dataset(
        tmp_path, include_sme=True
    )

    report = check_sme_feasibility.build_feasibility_report(
        dataset, metadata_path, dictionary
    )
    transaction = report["transaction_feasibility"]

    assert report["conclusion"]["identifiable_sme_customers_found"] is True
    assert transaction["transaction_file_opened"] is True
    assert transaction["matching_transaction_count"] == 2
    assert transaction["matched_sme_identifier_count"] == 1
    assert transaction["all_sme_identifiers_matched"] is True
    assert transaction["date_coverage"]["minimum"].startswith("2024-01-01")
    assert transaction["date_coverage"]["maximum"].startswith("2024-01-08")
    assert transaction["completeness"]["null_amount_count"] == 0


def test_cli_reports_are_deterministic_and_privacy_safe(tmp_path: Path) -> None:
    dataset, dictionary, metadata_path = prepare_dataset(
        tmp_path, include_sme=False
    )
    json_path = tmp_path / "output" / "sme.json"
    markdown_path = tmp_path / "output" / "sme.md"
    command = [
        sys.executable,
        "-B",
        str(SCRIPT),
        "--dataset-dir",
        str(dataset),
        "--metadata-report",
        str(metadata_path),
        "--dictionary",
        str(dictionary),
        "--json-report",
        str(json_path),
        "--markdown-report",
        str(markdown_path),
        "--batch-size",
        "2",
    ]

    first = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    first_json = json_path.read_text(encoding="utf-8")
    first_markdown = markdown_path.read_text(encoding="utf-8")
    second = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert json_path.read_text(encoding="utf-8") == first_json
    assert markdown_path.read_text(encoding="utf-8") == first_markdown
    assert str(tmp_path) not in first_json
    assert str(tmp_path) not in first_markdown
    assert "C1" not in first_json
    assert re.search(r"\b(?:CL|TX)\d{4,}\b", first_json) is None
    assert re.search(r"\b(?:CL|TX)\d{4,}\b", first_markdown) is None
    assert "No identifiable SME customers were found" in first_markdown


def test_implementation_avoids_pandas_and_full_table_reads() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "pandas" not in imported_modules
    assert called_attributes.isdisjoint(
        {"read", "read_table", "read_row_group", "read_pandas", "to_pandas"}
    )
