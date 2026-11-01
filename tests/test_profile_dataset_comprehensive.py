"""Tests for bounded comprehensive dataset profiling."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import inspect_parquet_metadata
from scripts import profile_dataset_comprehensive as profiler


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "profile_dataset_comprehensive.py"


def write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "student_export"
    dataset.mkdir()
    dictionary = dataset / "DATA_DICTIONARY.html"
    dictionary.write_text(
        """
<html><body>
<h2 id="customers">customers</h2>
<p>One row per customer. 2 rows.</p>
<table>
<tr><th>Column</th><th>Type</th><th>Description</th></tr>
<tr><td>client_id</td><td>string</td><td>Unique customer identifier.</td></tr>
<tr><td>segment</td><td>string</td><td>Customer segment including SME.</td></tr>
<tr><td>type_cd</td><td>string</td><td>Legal entity type.</td></tr>
<tr><td>bank_reg_dt</td><td>date</td><td>Bank registration date.</td></tr>
<tr><td>birth_or_reg_dt</td><td>date</td><td>Birth or registration date.</td></tr>
</table>
<h2 id="transactions">transactions</h2>
<p>Every financial event. 4 rows.</p>
<table>
<tr><th>Column</th><th>Type</th><th>Description</th></tr>
<tr><td>txn_id</td><td>string</td><td>Unique transaction identifier.</td></tr>
<tr><td>client_id_fk</td><td>string</td><td>Joins to customers.client_id.</td></tr>
<tr><td>book_date</td><td>date</td><td>Date the transaction was booked.</td></tr>
<tr><td>amount_eur</td><td>float</td><td>Amount converted to EUR.</td></tr>
<tr><td>dc_indicator</td><td>string</td><td>Direction. C credit and D debit.</td></tr>
<tr><td>trx_ccy</td><td>string</td><td>Currency.</td></tr>
<tr><td>year</td><td>int</td><td>Year.</td></tr>
<tr><td>month</td><td>int</td><td>Month.</td></tr>
</table>
<h2 id="margin_assets">margin_assets</h2>
<p>Monthly balance snapshots. 3 rows.</p>
<table>
<tr><th>Column</th><th>Type</th><th>Description</th></tr>
<tr><td>client_id_fk</td><td>string</td><td>Customer reference.</td></tr>
<tr><td>month_end</td><td>date</td><td>Month-end date.</td></tr>
<tr><td>end_balance_eur</td><td>float</td><td>End balance.</td></tr>
</table>
</body></html>
        """.strip(),
        encoding="utf-8",
    )
    pq.write_table(
        pa.table(
            {
                "client_id": ["C1", "C2"],
                "segment": ["SME", "Private"],
                "type_cd": ["H", "C"],
                "bank_reg_dt": pa.array(
                    [datetime(2024, 1, 1), datetime(2024, 2, 1)],
                    type=pa.timestamp("us"),
                ),
                "birth_or_reg_dt": pa.array(
                    [datetime(2025, 1, 1), datetime(2023, 1, 1)],
                    type=pa.timestamp("us"),
                ),
            }
        ),
        dataset / "customers.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "txn_id": ["T1", "T2", "T3", "T4"],
                "client_id_fk": ["C1", "C1", "C2", "C9"],
                "book_date": pa.array(
                    [
                        datetime(2024, 1, 1),
                        datetime(2024, 1, 2),
                        datetime(2024, 1, 3),
                        datetime(2024, 1, 4),
                    ],
                    type=pa.timestamp("ns"),
                ),
                "amount_eur": [10.0, 0.0, -2.0, 5.0],
                "dc_indicator": ["C", "D", "D", "X"],
                "trx_ccy": ["EUR", "EUR", "EUR", "EUR"],
                "year": [2024, 2024, 2024, 2024],
                "month": [1, 1, 1, 1],
            }
        ),
        dataset / "transactions.parquet",
        row_group_size=2,
    )
    pq.write_table(
        pa.table(
            {
                "client_id_fk": ["C1", "C1", "C9"],
                "month_end": pa.array(
                    [
                        datetime(2024, 1, 31),
                        datetime(2024, 1, 31),
                        datetime(2024, 2, 29),
                    ],
                    type=pa.timestamp("us"),
                ),
                "end_balance_eur": [1.0, 2.0, 3.0],
            }
        ),
        dataset / "margin_assets.parquet",
    )
    for name in (
        "leasing_agreements",
        "life_insurance",
        "property_insurance",
        "pension",
        "margin_liabilities",
    ):
        pq.write_table(
            pa.table(
                {
                    "client_id_fk": ["C1"],
                    "snapshot_date": pa.array(
                        [datetime(2024, 1, 31)], type=pa.timestamp("us")
                    ),
                    "value": [1.0],
                }
            ),
            dataset / f"{name}.parquet",
        )
    metadata = inspect_parquet_metadata.inspect_dataset(dataset, dictionary)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            inspect_parquet_metadata.summarise_report(metadata),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return dataset, metadata_path


def test_profiles_all_tables_and_column_statistics(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)

    report = profiler.build_comprehensive_report(
        dataset, metadata_path, batch_size=2
    )

    assert report["summary"]["parquet_file_count"] == 8
    assert report["summary"]["total_rows"] == 2 + 4 + 3 + 5
    transaction = next(
        table for table in report["tables"] if table["table_name"] == "transactions"
    )
    amount = transaction["columns"]["amount_eur"]
    assert amount["numeric_statistics"]["zero_count"] == 1
    assert amount["numeric_statistics"]["negative_count"] == 1
    assert transaction["columns"]["dc_indicator"]["unexpected_values"] == ["X"]
    customers = next(
        table for table in report["tables"] if table["table_name"] == "customers"
    )
    assert customers["data_quality"]["cross_field_checks"][
        "birth_or_registration_after_bank_registration"
    ] == 1
    assert {
        (item["type_cd"], item["segment"], item["count"])
        for item in customers["data_quality"]["type_cd_segment_counts"]
    } == {("H", "SME", 1), ("C", "Private", 1)}


def test_relationship_overlap_and_orphans_are_exact(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)

    report = profiler.build_comprehensive_report(
        dataset, metadata_path, batch_size=2
    )
    transaction = next(
        table for table in report["tables"] if table["table_name"] == "transactions"
    )
    relation = transaction["customer_relationship"]

    assert relation["matching_row_count"] == 3
    assert relation["orphan_row_count"] == 1
    assert relation["distinct_orphan_reference_count"] == 1
    assert relation["verified"] is False


def test_deterministic_reports_are_privacy_safe(tmp_path: Path) -> None:
    dataset, metadata_path = write_fixture(tmp_path)
    json_path = tmp_path / "output" / "analysis.json"
    markdown_path = tmp_path / "output" / "analysis.md"

    first = profiler.build_comprehensive_report(
        dataset, metadata_path, batch_size=2
    )
    profiler.write_reports(first, json_path, markdown_path)
    first_json = json_path.read_text(encoding="utf-8")
    first_markdown = markdown_path.read_text(encoding="utf-8")
    second = profiler.build_comprehensive_report(
        dataset, metadata_path, batch_size=2
    )
    profiler.write_reports(second, json_path, markdown_path)

    assert json_path.read_text(encoding="utf-8") == first_json
    assert markdown_path.read_text(encoding="utf-8") == first_markdown
    assert str(tmp_path) not in first_json
    assert str(tmp_path) not in first_markdown
    assert "T1" not in first_json
    assert "T1" not in first_markdown
    assert "## Relationship Matrix" in first_markdown
    assert "```mermaid" in first_markdown


def test_script_avoids_pandas_and_full_table_materialisation() -> None:
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
