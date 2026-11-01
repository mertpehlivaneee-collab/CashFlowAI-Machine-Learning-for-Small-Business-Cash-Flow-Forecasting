"""Consistency checks for Stage 02A specifications and measured evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "data"
README = ROOT / "README.md"
DISTRIBUTION_JSON = (
    ROOT
    / "reports"
    / "data_inspection"
    / "customer_distribution_analysis.json"
)
DISTRIBUTION_MD = (
    ROOT
    / "reports"
    / "data_inspection"
    / "customer_distribution_analysis.md"
)
TABLE_USAGE = DOCS / "table_usage_decision.md"
DATASET_SPEC = DOCS / "forecasting_dataset_specification.md"
PREPROCESSING_SPEC = DOCS / "preprocessing_specification.md"


def test_stage02a_deliverables_exist_and_are_linked() -> None:
    expected = (
        DISTRIBUTION_JSON,
        DISTRIBUTION_MD,
        TABLE_USAGE,
        DATASET_SPEC,
        PREPROCESSING_SPEC,
    )
    for path in expected:
        assert path.is_file(), f"Missing Stage 02A deliverable: {path}"

    readme = README.read_text(encoding="utf-8")
    for path in expected:
        assert path.relative_to(ROOT).as_posix() in readme


def test_customer_distribution_statistics_are_recorded() -> None:
    report = json.loads(DISTRIBUTION_JSON.read_text(encoding="utf-8"))
    activity = report["customer_activity"]

    assert report["customer_file"]["row_count"] == 200_000
    assert activity["active_customer_count"] == 200_000
    assert activity["zero_transaction_customer_count"] == 0
    assert activity["active_customer_weeks"] == 19_161_610
    assert activity["zero_activity_customer_weeks_in_full_window"] == 1_638_390
    assert activity["customers_active_in_both_years"] == 189_608
    assert (
        report["eligibility_sensitivity"]["recommended_eligibility"][
            "eligible_customer_count"
        ]
        == 189_608
    )
    assert report["calendar_definition"]["complete_week_count"] == 104
    assert (
        report["calendar_definition"]["partial_week_transaction_count"]
        == 708_047
    )


def test_table_usage_decision_covers_all_tables() -> None:
    text = TABLE_USAGE.read_text(encoding="utf-8")
    tables = (
        "customers.parquet",
        "transactions.parquet",
        "leasing_agreements.parquet",
        "life_insurance.parquet",
        "property_insurance.parquet",
        "pension.parquet",
        "margin_assets.parquet",
        "margin_liabilities.parquet",
    )

    for table in tables:
        assert table in text
    assert "Required" in text
    assert "Optional validated feature source" in text
    assert "Excluded from the initial model" in text


def test_dataset_and_preprocessing_rules_are_frozen() -> None:
    dataset = DATASET_SPEC.read_text(encoding="utf-8")
    preprocessing = PREPROCESSING_SPEC.read_text(encoding="utf-8")

    for text in (dataset, preprocessing):
        assert "next-week net bank-transaction cash flow" in text
        assert "Monday" in text
        assert "2025-12-28" in text
        assert "189,608" in text
        assert "customer-disjoint" in text or "customer partitions" in text
        assert "past-only" in text
        assert "MAE" in text and "RMSE" in text

    assert "202401" in dataset
    assert "70/15/15" in dataset
    assert "Do not silently drop duplicates" in preprocessing
    assert "Do not clip the target" in preprocessing
    assert "one row per eligible customer" in dataset


def test_stage02a_document_links_resolve() -> None:
    for document in (README, TABLE_USAGE, DATASET_SPEC, PREPROCESSING_SPEC):
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            path_text = target.split("#", 1)[0]
            assert (document.parent / path_text).resolve().exists(), (
                f"Broken local link {target!r} in {document.name}"
            )
