"""Tests for metadata-only Parquet inventory inspection."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import inspect_parquet_metadata


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "inspect_parquet_metadata.py"


def write_dictionary(path: Path) -> None:
    path.write_text(
        """
<!doctype html>
<html><body>
<h2 id="customers">customers</h2>
<p>One row per customer. 3 rows.</p>
<table>
  <tr><th>Column</th><th>Type</th><th>Description</th></tr>
  <tr><td>client_id</td><td>string</td>
      <td>Unique customer identifier. Used as a join key.</td></tr>
  <tr><td>segment</td><td>string</td>
      <td>Customer segment including SME.</td></tr>
</table>
<h2 id="transactions">transactions</h2>
<p>Every financial event. 4 rows.</p>
<table>
  <tr><th>Column</th><th>Type</th><th>Description</th></tr>
  <tr><td>txn_id</td><td>string</td>
      <td>Unique transaction identifier.</td></tr>
  <tr><td>client_id_fk</td><td>string</td>
      <td>Customer who owns the account. Joins to customers.client_id.</td></tr>
  <tr><td>amount_eur</td><td>float</td>
      <td>Amount in EUR.</td></tr>
  <tr><td>year</td><td>string</td>
      <td>Documented as a string for this fixture.</td></tr>
</table>
</body></html>
        """.strip(),
        encoding="utf-8",
    )


def write_fixture_dataset(dataset: Path) -> None:
    dataset.mkdir(parents=True)
    customers = pa.table(
        {
            "client_id": ["C1", "C2", "C3", "C4"],
            "segment": ["SME", "SME", "SME", "SME"],
        }
    )
    transactions = pa.table(
        {
            "txn_id": ["T1", "T2", "T3", "T4"],
            "client_id_fk": ["C1", "C1", "C2", "C2"],
            "amount_eur": [1.0, 2.0, 3.0, 4.0],
            "year": [2024, 2024, 2024, 2024],
            "month": [1, 1, 2, 2],
        }
    )
    pq.write_table(
        customers,
        dataset / "customers.parquet",
        row_group_size=2,
        write_statistics=True,
    )
    pq.write_table(
        transactions,
        dataset / "transactions.parquet",
        row_group_size=2,
        write_statistics=False,
    )
    write_dictionary(dataset / "DATA_DICTIONARY.html")


def test_inventory_captures_schemas_sizes_and_row_groups(tmp_path: Path) -> None:
    dataset = tmp_path / "student_export"
    write_fixture_dataset(dataset)

    report = inspect_parquet_metadata.inspect_dataset(
        dataset, dataset / "DATA_DICTIONARY.html"
    )

    assert report["summary"]["parquet_file_count"] == 2
    customers = report["files"][0]
    assert customers["table_name"] == "customers"
    assert customers["parquet_metadata"]["row_count"] == 4
    assert customers["parquet_metadata"]["row_group_count"] == 2
    assert customers["file_size_bytes"] > 0
    assert customers["columns"][0]["name"] == "client_id"
    assert customers["columns"][0]["arrow_type"] == "string"
    assert customers["columns"][0]["parquet_leaves"][0]["physical_type"] == "BYTE_ARRAY"
    assert customers["columns"][0]["nullable"] is True
    assert customers["columns"][0]["statistics_summary"]["global_min_max_complete"]
    assert all(group["row_count"] == 2 for group in customers["row_groups"])


def test_inventory_records_missing_statistics_without_guessing(tmp_path: Path) -> None:
    dataset = tmp_path / "student_export"
    write_fixture_dataset(dataset)

    report = inspect_parquet_metadata.inspect_dataset(
        dataset, dataset / "DATA_DICTIONARY.html"
    )
    transactions = report["files"][1]
    first_chunk = transactions["row_groups"][0]["column_chunks"][0]

    assert first_chunk["statistics"]["reported"] is False
    assert first_chunk["statistics"]["min_max_available"] is False
    assert "min" in first_chunk["statistics"]["unavailable"]
    assert first_chunk["statistics"]["null_count"] is None


def test_dictionary_reconciliation_identifies_mismatches(tmp_path: Path) -> None:
    dataset = tmp_path / "student_export"
    write_fixture_dataset(dataset)

    report = inspect_parquet_metadata.inspect_dataset(
        dataset, dataset / "DATA_DICTIONARY.html"
    )
    customers, transactions = report["files"]

    assert customers["dictionary"]["purpose"] == "One row per customer. 3 rows."
    assert customers["reconciliation"]["row_count_matches"] is False
    assert (
        transactions["reconciliation"]["documented_row_count"] == 4
    )
    assert transactions["reconciliation"][
        "schema_fields_absent_from_dictionary"
    ] == ["month"]
    assert transactions["reconciliation"]["dictionary_type_mismatches"] == [
        {
            "column": "year",
            "dictionary_type": "string",
            "arrow_type": "int64",
            "comparison": "coarse type families differ",
        }
    ]


def test_candidate_keys_and_relationships_are_unverified(tmp_path: Path) -> None:
    dataset = tmp_path / "student_export"
    write_fixture_dataset(dataset)

    report = inspect_parquet_metadata.inspect_dataset(
        dataset, dataset / "DATA_DICTIONARY.html"
    )
    customers, transactions = report["files"]

    assert customers["candidate_identifiers"][0]["column"] == "client_id"
    assert customers["candidate_identifiers"][0]["verified"] is False
    relationship = next(
        candidate
        for candidate in transactions["relationship_candidates"]
        if candidate["source_column"] == "client_id_fk"
    )
    assert relationship["target_table"] == "customers"
    assert relationship["target_column"] == "client_id"
    assert relationship["verified"] is False


def test_cli_reports_are_deterministic_and_path_free(tmp_path: Path) -> None:
    dataset = tmp_path / "private-root" / "student_export"
    write_fixture_dataset(dataset)
    json_path = tmp_path / "output" / "inventory.json"
    summary_path = tmp_path / "output" / "inventory_summary.json"
    markdown_path = tmp_path / "output" / "inventory.md"

    command = [
        sys.executable,
        "-B",
        str(SCRIPT),
        "--dataset-dir",
        str(dataset),
        "--dictionary",
        str(dataset / "DATA_DICTIONARY.html"),
        "--json-report",
        str(json_path),
        "--summary-json-report",
        str(summary_path),
        "--markdown-report",
        str(markdown_path),
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
    first_summary = summary_path.read_text(encoding="utf-8")
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
    assert summary_path.read_text(encoding="utf-8") == first_summary
    assert markdown_path.read_text(encoding="utf-8") == first_markdown
    assert str(tmp_path) not in first_json
    assert str(tmp_path) not in first_summary
    assert str(tmp_path) not in first_markdown
    parsed = json.loads(first_json)
    compact = json.loads(first_summary)
    assert parsed["inspection_mode"] == "metadata_only"
    assert compact["report_kind"] == "compact_summary"
    assert "row_groups" in parsed["files"][0]
    assert "row_groups" not in compact["files"][0]
    assert "row_group_summary" in compact["files"][0]
    assert "## Table: `customers`" in first_markdown
    assert "Unique customer identifier" in first_markdown


def test_implementation_does_not_call_table_materialisation_methods() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called_attributes.isdisjoint(
        {"read", "read_table", "read_row_group", "read_pandas", "to_pandas"}
    )
