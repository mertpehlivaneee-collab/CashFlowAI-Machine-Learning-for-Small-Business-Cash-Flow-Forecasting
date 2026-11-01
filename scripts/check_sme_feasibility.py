#!/usr/bin/env python3
"""Run a focused, aggregate-only SME feasibility check."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


DATASET_DIR = Path("synthetic_banking/student_export")
METADATA_REPORT = Path(
    "reports/data_inspection/parquet_inventory_summary.json"
)
DICTIONARY_PATH = DATASET_DIR / "DATA_DICTIONARY.html"
JSON_REPORT = Path("reports/data_inspection/sme_feasibility.json")
MARKDOWN_REPORT = Path("reports/data_inspection/sme_feasibility.md")
DEFAULT_BATCH_SIZE = 65_536
DOCUMENTED_SEGMENT_LABELS = ("Private", "SME", "Corporate")


class PlainTextParser(HTMLParser):
    """Extract visible dictionary text without executing or loading resources."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif not self._skip_depth and tag in {
            "p",
            "div",
            "br",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "td",
            "th",
        }:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self._parts).split())


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _sanitize_evidence(text: str) -> str:
    return re.sub(
        r"\b(?:CL|TX)\d{4,}\b",
        "[identifier example omitted]",
        text,
    )


def _load_metadata(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report.get("files"), list):
        raise ValueError("Metadata report does not contain a files list")
    return report


def _table(metadata: dict[str, Any], table_name: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in metadata["files"]
            if item.get("table_name") == table_name
        ),
        None,
    )


def _find_column(
    table: dict[str, Any],
    *,
    preferred_name: str,
    description_terms: tuple[str, ...],
) -> tuple[str, str]:
    columns = table.get("columns", [])
    preferred = next(
        (column for column in columns if column.get("name") == preferred_name),
        None,
    )

    def matches(column: dict[str, Any]) -> bool:
        description = (column.get("dictionary_description") or "").lower()
        return all(term.lower() in description for term in description_terms)

    selected = preferred if preferred is not None and matches(preferred) else None
    if selected is None:
        candidates = [column for column in columns if matches(column)]
        if len(candidates) != 1:
            raise ValueError(
                f"Could not identify one column for {description_terms!r} "
                f"in {table.get('table_name')}"
            )
        selected = candidates[0]

    evidence = _sanitize_evidence(
        f"Task 2B schema column {selected['name']!r} matched dictionary "
        f"description: {selected.get('dictionary_description')}"
    )
    return str(selected["name"]), evidence


def identify_columns(metadata: dict[str, Any]) -> dict[str, Any]:
    """Identify required fields from the accepted Task 2B metadata report."""

    customers = _table(metadata, "customers")
    transactions = _table(metadata, "transactions")
    if customers is None:
        raise ValueError("Metadata report does not contain the customers table")

    customer_id, customer_id_evidence = _find_column(
        customers,
        preferred_name="client_id",
        description_terms=("unique", "customer", "identifier"),
    )
    segment, segment_evidence = _find_column(
        customers,
        preferred_name="segment",
        description_terms=("customer segment",),
    )

    transaction_fields: dict[str, str] = {}
    transaction_evidence: dict[str, str] = {}
    if transactions is not None:
        definitions = {
            "transaction_id": (
                "txn_id",
                ("unique", "transaction", "identifier"),
            ),
            "customer_reference": (
                "client_id_fk",
                ("joins to customers.client_id",),
            ),
            "date": ("book_date", ("date the transaction was booked",)),
            "amount": ("amount_eur", ("amount converted to eur",)),
            "direction": ("dc_indicator", ("direction. c credit",)),
        }
        for concept, (preferred_name, terms) in definitions.items():
            name, evidence = _find_column(
                transactions,
                preferred_name=preferred_name,
                description_terms=terms,
            )
            transaction_fields[concept] = name
            transaction_evidence[concept] = evidence

    return {
        "customer": {
            "identifier": customer_id,
            "segment": segment,
        },
        "transaction": transaction_fields,
        "evidence": {
            "customer_identifier": customer_id_evidence,
            "customer_segment": segment_evidence,
            **transaction_evidence,
        },
    }


def _dictionary_claims(
    path: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    parser = PlainTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="strict"))
    parser.close()
    text = parser.text

    match = re.search(
        r"Customer Segments\s+Private\s+([\d,]+)\s+"
        r"SME\s+([\d,]+)\s+Corporate\s+([\d,]+)",
        text,
        re.IGNORECASE,
    )
    segment_counts: dict[str, int] = {}
    if match:
        segment_counts = {
            "Private": int(match.group(1).replace(",", "")),
            "SME": int(match.group(2).replace(",", "")),
            "Corporate": int(match.group(3).replace(",", "")),
        }

    customers = _table(metadata, "customers")
    documented_customer_count = (
        customers.get("reconciliation", {}).get("documented_row_count")
        if customers is not None
        else None
    )
    return {
        "source": path.name,
        "documented_segment_labels": list(DOCUMENTED_SEGMENT_LABELS),
        "documented_segment_counts": segment_counts,
        "documented_customer_count": documented_customer_count,
        "documented_sme_customer_count": segment_counts.get("SME"),
        "status": "dictionary_claim_not_verified",
    }


def scan_customers(
    path: Path,
    identifier_column: str,
    segment_column: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Aggregate segment and identifier properties from two selected columns."""

    parquet_file = pq.ParquetFile(path)
    missing = {
        identifier_column,
        segment_column,
    } - set(parquet_file.schema_arrow.names)
    if missing:
        raise ValueError(f"Customers file is missing required columns: {sorted(missing)}")

    total_rows = 0
    segment_counts: Counter[Any] = Counter()
    identifier_values: set[Any] = set()
    sme_identifiers: set[Any] = set()
    null_identifiers = 0
    blank_identifiers = 0
    sme_rows_with_missing_identifier = 0

    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=[identifier_column, segment_column],
    ):
        identifiers = batch.column(identifier_column).to_pylist()
        segments = batch.column(segment_column).to_pylist()
        total_rows += batch.num_rows

        for identifier, segment in zip(identifiers, segments):
            segment_counts[segment] += 1
            if identifier is None:
                null_identifiers += 1
            elif identifier == "":
                blank_identifiers += 1
                identifier_values.add(identifier)
            else:
                identifier_values.add(identifier)

            if segment == "SME":
                if identifier is None or identifier == "":
                    sme_rows_with_missing_identifier += 1
                else:
                    sme_identifiers.add(identifier)

    non_null_identifiers = total_rows - null_identifiers
    duplicate_identifier_rows = max(
        0, non_null_identifiers - len(identifier_values)
    )
    segment_rows = [
        {"value": _json_safe(value), "count": count}
        for value, count in sorted(
            segment_counts.items(),
            key=lambda item: (
                item[0] is None,
                "" if item[0] is None else str(item[0]),
            ),
        )
    ]
    null_segments = segment_counts.get(None, 0)
    return {
        "actual_customer_count": total_rows,
        "segment_counts": segment_rows,
        "null_segment_count": null_segments,
        "sme_labelled_customer_rows": segment_counts.get("SME", 0),
        "sme_unique_identifier_count": len(sme_identifiers),
        "sme_rows_with_missing_identifier": sme_rows_with_missing_identifier,
        "identifier_null_count": null_identifiers,
        "identifier_blank_count": blank_identifiers,
        "identifier_non_null_count": non_null_identifiers,
        "identifier_unique_non_null_count": len(identifier_values),
        "identifier_duplicate_row_count": duplicate_identifier_rows,
        "identifier_is_unique": (
            null_identifiers == 0 and duplicate_identifier_rows == 0
        ),
        "_sme_identifiers": sme_identifiers,
    }


def _min_date(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _max_date(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def scan_sme_transactions(
    path: Path,
    fields: dict[str, str],
    sme_identifiers: set[Any],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Aggregate transactions linked to SME identifiers without materialising rows."""

    required_columns = list(fields.values())
    dataset = ds.dataset(path, format="parquet")
    missing = set(required_columns) - set(dataset.schema.names)
    if missing:
        raise ValueError(
            f"Transactions file is missing required columns: {sorted(missing)}"
        )

    customer_reference = fields["customer_reference"]
    scanner = dataset.scanner(
        columns=required_columns,
        filter=ds.field(customer_reference).isin(sorted(sme_identifiers)),
        batch_size=batch_size,
        use_threads=True,
    )

    matched_transactions = 0
    matched_identifiers: set[Any] = set()
    null_transaction_ids = 0
    null_dates = 0
    null_amounts = 0
    null_directions = 0
    directions: Counter[Any] = Counter()
    minimum_date: Any = None
    maximum_date: Any = None

    for batch in scanner.to_batches():
        matched_transactions += batch.num_rows
        transaction_ids = batch.column(fields["transaction_id"]).to_pylist()
        references = batch.column(customer_reference).to_pylist()
        dates = batch.column(fields["date"]).to_pylist()
        amounts = batch.column(fields["amount"]).to_pylist()
        direction_values = batch.column(fields["direction"]).to_pylist()

        null_transaction_ids += sum(value is None for value in transaction_ids)
        null_amounts += sum(value is None for value in amounts)
        null_directions += sum(value is None for value in direction_values)
        for reference, booked_date, direction in zip(
            references, dates, direction_values
        ):
            if reference is not None:
                matched_identifiers.add(reference)
            if booked_date is None:
                null_dates += 1
            else:
                minimum_date = _min_date(minimum_date, booked_date)
                maximum_date = _max_date(maximum_date, booked_date)
            directions[_json_safe(direction)] += 1

    unmatched_identifiers = len(set(sme_identifiers) - matched_identifiers)
    return {
        "status": "linkage_tested",
        "transaction_file_opened": True,
        "matching_transaction_count": matched_transactions,
        "sme_identifier_count": len(set(sme_identifiers)),
        "matched_sme_identifier_count": len(matched_identifiers),
        "unmatched_sme_identifier_count": unmatched_identifiers,
        "all_sme_identifiers_matched": unmatched_identifiers == 0,
        "linkage_feasible": matched_transactions > 0,
        "date_coverage": {
            "minimum": _json_safe(minimum_date),
            "maximum": _json_safe(maximum_date),
            "null_date_count": null_dates,
        },
        "completeness": {
            "null_transaction_identifier_count": null_transaction_ids,
            "null_amount_count": null_amounts,
            "null_direction_count": null_directions,
            "direction_counts": [
                {"value": value, "count": count}
                for value, count in sorted(
                    directions.items(),
                    key=lambda item: (item[0] is None, str(item[0])),
                )
            ],
        },
        "read_mode": (
            "PyArrow dataset scanner with selected columns and a row-level "
            "customer-reference filter"
        ),
    }


def build_feasibility_report(
    dataset_dir: Path,
    metadata_report_path: Path,
    dictionary_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    metadata = _load_metadata(metadata_report_path)
    selected_columns = identify_columns(metadata)
    customers_path = dataset_dir / "customers.parquet"
    if not customers_path.is_file():
        raise ValueError("customers.parquet not found")

    customer_scan = scan_customers(
        customers_path,
        selected_columns["customer"]["identifier"],
        selected_columns["customer"]["segment"],
        batch_size=batch_size,
    )
    sme_identifiers = customer_scan.pop("_sme_identifiers")
    claims = _dictionary_claims(dictionary_path, metadata)

    observed_segments = {
        item["value"]: item["count"]
        for item in customer_scan["segment_counts"]
        if item["value"] is not None
    }
    observed_labels = set(observed_segments)
    documented_labels = set(claims["documented_segment_labels"])
    segment_reconciliation = {
        "all_observed_values_documented": observed_labels <= documented_labels,
        "all_documented_values_observed": documented_labels <= observed_labels,
        "unexpected_observed_values": sorted(observed_labels - documented_labels),
        "missing_documented_values": sorted(documented_labels - observed_labels),
        "segment_counts_match": (
            bool(claims["documented_segment_counts"])
            and observed_segments == claims["documented_segment_counts"]
        ),
        "customer_count_matches": (
            claims["documented_customer_count"]
            == customer_scan["actual_customer_count"]
        ),
        "null_segments_agree": customer_scan["null_segment_count"] == 0,
    }
    sme_found = customer_scan["sme_unique_identifier_count"] > 0

    transaction_result: dict[str, Any]
    transactions_path = dataset_dir / "transactions.parquet"
    if sme_found:
        if not selected_columns["transaction"]:
            raise ValueError(
                "Task 2B metadata does not identify the transaction fields"
            )
        if not transactions_path.is_file():
            raise ValueError("SME identifiers exist but transactions.parquet is absent")
        transaction_result = scan_sme_transactions(
            transactions_path,
            selected_columns["transaction"],
            sme_identifiers,
            batch_size=batch_size,
        )
    else:
        transactions = _table(metadata, "transactions")
        transaction_result = {
            "status": "not_tested_no_identifiable_sme_customers",
            "transaction_file_opened": False,
            "reason": (
                "No row in customers.parquet has an exact segment label of SME, "
                "so there is no defensible SME identifier set for a transaction "
                "filter."
            ),
            "metadata_context": {
                "transaction_file_present": transactions_path.is_file(),
                "metadata_row_count": (
                    transactions.get("parquet_metadata", {}).get("row_count")
                    if transactions is not None
                    else None
                ),
            },
            "smallest_justified_next_diagnostic": (
                "Confirm the dataset export version and completeness with the "
                "source provider. Customers.parquet contains 200,000 Private "
                "customers but no documented SME or Corporate labels. Scanning "
                "transactions cannot recover a missing customer segment label."
            ),
        }

    return {
        "report_schema_version": "1.0",
        "task": "2C-1",
        "inspection_mode": "focused_record_level_read_only",
        "dataset_name": dataset_dir.name,
        "metadata_report": metadata_report_path.name,
        "selected_columns": selected_columns,
        "verified_findings": customer_scan,
        "dictionary_claims": claims,
        "customer_segment_reconciliation": segment_reconciliation,
        "transaction_feasibility": transaction_result,
        "conclusion": {
            "identifiable_sme_customers_found": sme_found,
            "sme_selection_status": "not_performed",
            "transaction_linkage_status": transaction_result["status"],
            "material_dataset_limitation": (
                not sme_found
                and segment_reconciliation["all_observed_values_documented"]
                and observed_labels == {"Private"}
            ),
        },
        "limitations": [
            "Only customer identifier and segment columns were scanned for the "
            "customer feasibility result.",
            "Dictionary claims are kept separate from verified record aggregates.",
            "No SME selection, cleaning, aggregation, feature engineering, "
            "model training, or transaction export was performed.",
            (
                "Transactions were not opened because no identifiable SME "
                "customer was found."
                if not sme_found
                else "Transaction linkage was checked only for the discovered "
                "SME-labelled identifiers."
            ),
        ],
    }


def _format_segment_counts(rows: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{row['value'] if row['value'] is not None else 'null'}: {row['count']:,}"
        for row in rows
    )


def _format_dictionary_segment_counts(counts: dict[str, int]) -> str:
    return (
        "; ".join(
            f"{name}: {count:,}" for name, count in counts.items()
        )
        if counts
        else "Unavailable"
    )


def render_markdown(report: dict[str, Any]) -> str:
    customer = report["verified_findings"]
    claims = report["dictionary_claims"]
    reconciliation = report["customer_segment_reconciliation"]
    transaction = report["transaction_feasibility"]
    conclusion = report["conclusion"]

    lines = [
        "# CashFlowAI SME Feasibility Verification",
        "",
        "## Material Finding",
        "",
    ]
    if conclusion["identifiable_sme_customers_found"]:
        lines.append(
            f"Identifiable SME-labelled customers were found: "
            f"{customer['sme_unique_identifier_count']:,} unique identifiers."
        )
    else:
        lines.append(
            "No identifiable SME customers were found. The extracted "
            "customers table contains only `Private` segment labels, so SME "
            "selection and transaction linkage are not feasible with this file."
        )

    lines.extend(
        [
            "",
            "## Verified Findings",
            "",
            "| Measure | Verified value |",
            "| --- | ---: |",
            f"| Customer rows scanned | {customer['actual_customer_count']:,} |",
            f"| Segment values and counts | "
            f"{_format_segment_counts(customer['segment_counts'])} |",
            f"| Null segment labels | {customer['null_segment_count']:,} |",
            f"| SME-labelled rows | {customer['sme_labelled_customer_rows']:,} |",
            f"| Unique SME identifiers | "
            f"{customer['sme_unique_identifier_count']:,} |",
            f"| Null customer identifiers | "
            f"{customer['identifier_null_count']:,} |",
            f"| Blank customer identifiers | "
            f"{customer['identifier_blank_count']:,} |",
            f"| Unique non-null customer identifiers | "
            f"{customer['identifier_unique_non_null_count']:,} |",
            f"| Duplicate identifier rows | "
            f"{customer['identifier_duplicate_row_count']:,} |",
            f"| Identifier uniqueness confirmed | "
            f"{customer['identifier_is_unique']} |",
            "",
            "These values are direct aggregates from the selected "
            f"`{report['selected_columns']['customer']['identifier']}` and "
            f"`{report['selected_columns']['customer']['segment']}` columns.",
            "",
            "## Data Dictionary Claims",
            "",
            "Dictionary values below are claims from "
            f"`{claims['source']}` and are not record-verified findings.",
            "",
            f"- Documented customer rows: "
            f"{claims['documented_customer_count']:,}"
            if claims["documented_customer_count"] is not None
            else "- Documented customer rows: Unavailable",
            f"- Documented segment labels: "
            f"{', '.join(claims['documented_segment_labels'])}",
            f"- Documented segment counts: "
            f"{_format_dictionary_segment_counts(claims['documented_segment_counts'])}",
            "",
            "## Segment Reconciliation",
            "",
            f"- All observed values documented: "
            f"{reconciliation['all_observed_values_documented']}",
            f"- All documented values observed: "
            f"{reconciliation['all_documented_values_observed']}",
            f"- Unexpected observed values: "
            f"{reconciliation['unexpected_observed_values'] or 'None'}",
            f"- Missing documented values: "
            f"{reconciliation['missing_documented_values'] or 'None'}",
            f"- Segment counts match: "
            f"{reconciliation['segment_counts_match']}",
            f"- Customer count matches: "
            f"{reconciliation['customer_count_matches']}",
            "",
            "## Transaction Linkage Feasibility",
            "",
            f"- Status: `{transaction['status']}`",
            f"- Transactions file opened: "
            f"{transaction['transaction_file_opened']}",
        ]
    )
    if transaction["status"] == "linkage_tested":
        lines.extend(
            [
                f"- Matching transactions: "
                f"{transaction['matching_transaction_count']:,}",
                f"- SME identifiers matched: "
                f"{transaction['matched_sme_identifier_count']:,} of "
                f"{transaction['sme_identifier_count']:,}",
                f"- All SME identifiers matched: "
                f"{transaction['all_sme_identifiers_matched']}",
                f"- Date coverage: "
                f"{transaction['date_coverage']['minimum']} to "
                f"{transaction['date_coverage']['maximum']}",
                f"- Null transaction dates: "
                f"{transaction['date_coverage']['null_date_count']:,}",
                f"- Null amounts: "
                f"{transaction['completeness']['null_amount_count']:,}",
                f"- Null directions: "
                f"{transaction['completeness']['null_direction_count']:,}",
            ]
        )
    else:
        lines.extend(
            [
                f"- Reason: {transaction['reason']}",
                "- The complete transactions file was not scanned.",
            ]
        )

    lines.extend(
        [
            "",
            "## Smallest Next Diagnostic",
            "",
            (
                transaction["smallest_justified_next_diagnostic"]
                if "smallest_justified_next_diagnostic" in transaction
                else "Review any unmatched SME identifiers and transaction "
                "completeness before selecting the final cohort."
            ),
            "",
            "## Scope and Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    lines.extend(
        [
            "",
            "The report contains aggregate values only. Customer identifiers "
            "and transaction records are not published.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    report: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    json_path.write_text(json_text + "\n", encoding="utf-8", newline="\n")
    markdown_path.write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify customer segment availability and, only when SME labels "
            "exist, aggregate transaction linkage feasibility."
        )
    )
    parser.add_argument(
        "--dataset-dir", type=Path, default=DATASET_DIR
    )
    parser.add_argument(
        "--metadata-report", type=Path, default=METADATA_REPORT
    )
    parser.add_argument(
        "--dictionary", type=Path, default=DICTIONARY_PATH
    )
    parser.add_argument(
        "--json-report", type=Path, default=JSON_REPORT
    )
    parser.add_argument(
        "--markdown-report", type=Path, default=MARKDOWN_REPORT
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        dataset = args.dataset_dir.resolve()
        for report_path in (args.json_report, args.markdown_report):
            if report_path.resolve().is_relative_to(dataset):
                raise ValueError("Report output must be outside the source dataset")
        if args.batch_size <= 0:
            raise ValueError("Batch size must be positive")

        report = build_feasibility_report(
            args.dataset_dir,
            args.metadata_report,
            args.dictionary,
            batch_size=args.batch_size,
        )
        write_reports(report, args.json_report, args.markdown_report)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        pa.ArrowException,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    customer = report["verified_findings"]
    print(f"Customers scanned: {customer['actual_customer_count']}")
    print(f"SME-labelled customers: {customer['sme_labelled_customer_rows']}")
    print(
        "Transaction status: "
        f"{report['transaction_feasibility']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
