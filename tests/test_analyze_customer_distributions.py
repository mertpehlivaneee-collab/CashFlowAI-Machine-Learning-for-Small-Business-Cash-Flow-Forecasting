"""Tests for customer-level distribution analysis."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import analyze_customer_distributions as analysis
from scripts import inspect_parquet_metadata


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_customer_distributions.py"


def write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "student_export"
    dataset.mkdir()
    dictionary = dataset / "DATA_DICTIONARY.html"
    dictionary.write_text(
        """
<html><body>
<h2 id="customers">customers</h2>
<p>One row per customer. 3 rows.</p>
<table>
<tr><th>Column</th><th>Type</th><th>Description</th></tr>
<tr><td>client_id</td><td>string</td><td>Unique customer identifier.</td></tr>
<tr><td>segment</td><td>string</td><td>Customer segment.</td></tr>
</table>
<h2 id="transactions">transactions</h2>
<p>Every financial event. 6 rows.</p>
<table>
<tr><th>Column</th><th>Type</th><th>Description</th></tr>
<tr><td>txn_id</td><td>string</td><td>Unique transaction identifier.</td></tr>
<tr><td>client_id_fk</td><td>string</td><td>Joins to customers.client_id.</td></tr>
<tr><td>book_date</td><td>date</td><td>Date the transaction was booked.</td></tr>
<tr><td>amount_eur</td><td>float</td><td>Amount converted to EUR.</td></tr>
<tr><td>dc_indicator</td><td>string</td><td>Direction. C credit and D debit.</td></tr>
</table>
</body></html>
        """.strip(),
        encoding="utf-8",
    )
    pq.write_table(
        pa.table(
            {
                "client_id": ["C1", "C2", "C3"],
                "segment": ["Private", "Private", "Private"],
            }
        ),
        dataset / "customers.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "txn_id": ["T1", "T2", "T3", "T4", "T5", "T6"],
                "client_id_fk": ["C1", "C1", "C1", "C2", "C2", "C9"],
                "book_date": pa.array(
                    [
                        datetime(2024, 1, 1),
                        datetime(2024, 1, 2),
                        datetime(2024, 1, 9),
                        datetime(2024, 1, 3),
                        datetime(2025, 1, 2),
                        datetime(2024, 1, 4),
                    ],
                    type=pa.timestamp("ns"),
                ),
                "amount_eur": [100.0, 20.0, 5.0, 50.0, 10.0, 99.0],
                "dc_indicator": ["C", "D", "C", "D", "C", "D"],
            }
        ),
        dataset / "transactions.parquet",
        row_group_size=2,
    )
    metadata = inspect_parquet_metadata.inspect_dataset(dataset, dictionary)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(inspect_parquet_metadata.summarise_report(metadata), indent=2)
        + "\n",
        encoding="utf-8",
    )
    return dataset, metadata_path


def test_customer_activity_and_weekly_counts(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)

    report = analysis.build_analysis(dataset, metadata_path, batch_size=2)

    assert report["customer_file"]["row_count"] == 3
    assert report["transaction_scan"]["rows_scanned"] == 6
    assert report["transaction_scan"]["orphan_customer_rows"] == 1
    activity = report["customer_activity"]
    assert activity["active_customer_count"] == 2
    assert activity["zero_transaction_customer_count"] == 1
    assert activity["customers_active_in_both_years"] == 1
    assert activity["active_customer_weeks"] == 4


def test_weekly_net_cash_flow_and_amount_extremes(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)

    report = analysis.build_analysis(dataset, metadata_path, batch_size=2)

    weekly = report["customer_activity"]["weekly_net_cash_flow_active_weeks"]
    assert weekly["active_week_count"] == 4
    assert weekly["exact_maximum"] == 80.0
    assert weekly["exact_minimum"] == -50.0
    assert report["amount_distribution"]["exact_maximum"] == 100.0
    assert report["amount_distribution"]["negative_count"] == 0


def test_reports_are_deterministic_and_privacy_safe(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)
    json_path = tmp_path / "output" / "distribution.json"
    markdown_path = tmp_path / "output" / "distribution.md"

    first = analysis.build_analysis(dataset, metadata_path, batch_size=2)
    analysis.write_reports(first, json_path, markdown_path)
    first_json = json_path.read_text(encoding="utf-8")
    first_markdown = markdown_path.read_text(encoding="utf-8")
    second = analysis.build_analysis(dataset, metadata_path, batch_size=2)
    analysis.write_reports(second, json_path, markdown_path)

    assert json_path.read_text(encoding="utf-8") == first_json
    assert markdown_path.read_text(encoding="utf-8") == first_markdown
    assert str(tmp_path) not in first_json
    assert str(tmp_path) not in first_markdown
    assert "T1" not in first_json
    assert "C1" not in first_json
    assert "Weekly Net Cash-Flow Distribution" in first_markdown


def test_script_avoids_pandas_and_full_table_reads() -> None:
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
