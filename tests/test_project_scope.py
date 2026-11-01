"""Tests that active project scope and historical evidence remain consistent."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DECISION = ROOT / "docs" / "project_management" / "scope_change_decision.md"
NEW_TITLE = "CashFlowAI: Machine Learning for Personal Cash-Flow Forecasting"
NEW_QUESTION = (
    "How accurately can machine-learning models forecast the next week's net "
    "bank-transaction cash flow for individual banking customers compared "
    "with simple forecasting methods?"
)


def _normalised(text: str) -> str:
    return re.sub(r"\s+|>", "", text)


def test_active_readme_uses_current_scope() -> None:
    readme = README.read_text(encoding="utf-8")

    assert readme.splitlines()[0] == f"# {NEW_TITLE}"
    assert _normalised(NEW_QUESTION) in _normalised(readme)
    assert "Eligible records are Private customers only" in readme
    assert "scope_change_decision.md" in readme


def test_scope_decision_records_old_and_new_specifications() -> None:
    decision = DECISION.read_text(encoding="utf-8")

    assert (
        "CashFlowAI: Machine Learning for Small Business Cash-Flow Forecasting"
        in decision
    )
    assert NEW_TITLE in decision
    assert _normalised(NEW_QUESTION) in _normalised(decision)
    assert "academic approval" in decision.lower()
    assert "200,000" in decision
    assert "zero SME-labelled" in decision


def test_active_documents_define_global_panel_methodology() -> None:
    required_fragments = (
        "single global panel time-series regression model",
        "full available customer population",
        "customer-disjoint",
        "deterministic seed",
        "2024 and 2025",
        "past-only",
        "previously unseen customers",
        "future-year generalization",
        "at least two simple forecasting baselines",
        "MAE and RMSE",
        "customers.parquet",
        "transactions.parquet",
        "per-customer error distributions",
        "reproducible forecasting pipeline",
        "dashboard",
        "negative weekly net cash flow",
        "insufficient account",
    )
    for document in (README, DECISION):
        text = " ".join(document.read_text(encoding="utf-8").lower().split())
        for fragment in required_fragments:
            assert " ".join(fragment.lower().split()) in text, (
                f"Missing methodology statement {fragment!r} in {document.name}"
            )
        assert "at most five" not in text
        assert "no more than five" not in text
        assert "selected customers" not in text


def test_historical_sme_evidence_is_preserved() -> None:
    proposal = ROOT / "CashFlowAI_Final_Project_Proposal.docx"
    weekly_plan = ROOT / "CashFlowAI_Task_Division_Weekly_Plan.docx"
    sme_report = ROOT / "reports" / "data_inspection" / "sme_feasibility.md"
    analysis = (
        ROOT
        / "reports"
        / "data_inspection"
        / "comprehensive_dataset_analysis.md"
    )

    with zipfile.ZipFile(proposal) as document:
        proposal_text = document.read("word/document.xml").decode(
            "utf-8", errors="replace"
        )
    with zipfile.ZipFile(weekly_plan) as document:
        plan_text = document.read("word/document.xml").decode(
            "utf-8", errors="replace"
        )

    assert "Small Business Cash-Flow Forecasting" in proposal_text
    assert "simulated SMEs" in plan_text
    assert "No identifiable SME customers were found" in sme_report.read_text(
        encoding="utf-8"
    )
    assert "SME Discrepancy Investigation" in analysis.read_text(
        encoding="utf-8"
    )


def test_local_markdown_links_resolve() -> None:
    for document in (README, DECISION):
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            path_text = target.split("#", 1)[0]
            assert (document.parent / path_text).resolve().exists(), (
                f"Broken local link {target!r} in {document.name}"
            )
