#!/usr/bin/env python3
"""Inspect extracted Parquet metadata without materialising table records."""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq


JSON_REPORT = Path("reports/data_inspection/parquet_inventory.json")
SUMMARY_JSON_REPORT = Path(
    "reports/data_inspection/parquet_inventory_summary.json"
)
MARKDOWN_REPORT = Path("reports/data_inspection/parquet_inventory.md")
MAX_DICTIONARY_BYTES = 2 * 1024 * 1024
DATASET_DIR = Path("synthetic_banking/student_export")
DICTIONARY_PATH = DATASET_DIR / "DATA_DICTIONARY.html"


@dataclass(frozen=True, slots=True)
class DictionaryField:
    declared_type: str
    description: str


@dataclass(frozen=True, slots=True)
class DictionaryTable:
    name: str
    purpose: str
    documented_rows: int | None
    fields: dict[str, DictionaryField]


class DataDictionaryParser(HTMLParser):
    """Extract table purposes and documented column rows from the local HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: dict[str, DictionaryTable] = {}
        self._skip_depth = 0
        self._heading_parts: list[str] | None = None
        self._current_heading = ""
        self._purpose_parts: list[str] = []
        self._capture_purpose = False
        self._in_table = False
        self._table_consumed = False
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    @staticmethod
    def _normalise(parts: Iterable[str]) -> str:
        return " ".join("".join(parts).split())

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "h2":
            self._heading_parts = []
            self._current_heading = ""
            self._purpose_parts = []
            self._capture_purpose = False
            self._table_consumed = False
        elif tag == "p" and self._current_heading and not self._table_consumed:
            self._capture_purpose = True
        elif tag == "table" and self._current_heading and not self._table_consumed:
            self._in_table = True
            self._table_consumed = True
            self._rows = []
        elif tag == "tr" and self._in_table:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return

        if tag == "h2" and self._heading_parts is not None:
            self._current_heading = self._normalise(self._heading_parts)
            self._heading_parts = None
            self._capture_purpose = True
        elif tag == "p" and self._capture_purpose:
            self._capture_purpose = False
        elif tag in {"td", "th"} and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(self._normalise(self._cell_parts))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._in_table:
            self._finish_table()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._heading_parts is not None:
            self._heading_parts.append(data)
        if self._capture_purpose:
            self._purpose_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def _finish_table(self) -> None:
        self._in_table = False
        heading = self._current_heading
        purpose = self._normalise(self._purpose_parts)
        fields: dict[str, DictionaryField] = {}

        for row in self._rows:
            if len(row) < 3:
                continue
            if row[0].lower() == "column":
                continue
            fields[row[0]] = DictionaryField(
                declared_type=row[1],
                description=row[2],
            )

        if heading and fields:
            row_match = re.search(
                r"\b([\d,]+(?:\.\d+)?)\s*([MK])?\s+rows?\b",
                purpose,
                re.IGNORECASE,
            )
            if row_match:
                multiplier = {"M": 1_000_000, "K": 1_000}.get(
                    (row_match.group(2) or "").upper(), 1
                )
                documented_rows = int(
                    float(row_match.group(1).replace(",", "")) * multiplier
                )
            else:
                documented_rows = None
            self.tables[heading] = DictionaryTable(
                name=heading,
                purpose=purpose,
                documented_rows=documented_rows,
                fields=fields,
            )


def parse_dictionary(path: Path) -> dict[str, DictionaryTable]:
    """Parse the local dictionary without executing HTML or loading resources."""

    size = path.stat().st_size
    if size > MAX_DICTIONARY_BYTES:
        raise ValueError(
            f"Dictionary size {size} exceeds the {MAX_DICTIONARY_BYTES}-byte limit"
        )

    parser = DataDictionaryParser()
    parser.feed(path.read_text(encoding="utf-8", errors="strict"))
    parser.close()
    return parser.tables


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
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "binary_base64": base64.b64encode(value).decode("ascii"),
                "byte_length": len(value),
            }
    if isinstance(value, dict):
        return {
            str(_json_safe(key)): _json_safe(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _metadata_items(metadata: Any) -> list[dict[str, Any]]:
    if metadata is None:
        return []

    try:
        items = metadata.items()
    except AttributeError:
        return [{"value": _json_safe(metadata)}]

    output: list[dict[str, Any]] = []
    for key, value in sorted(items, key=lambda item: str(item[0])):
        key_text = _json_safe(key)
        safe_value = _json_safe(value)
        if isinstance(safe_value, str):
            output.append(
                {
                    "key": key_text,
                    "value": safe_value,
                    "truncated": False,
                }
            )
        else:
            output.append({"key": key_text, "value": safe_value})
    return output


def _arrow_type_children(data_type: pa.DataType) -> list[pa.Field]:
    if pa.types.is_struct(data_type):
        return [data_type.field(index) for index in range(data_type.num_fields)]
    if pa.types.is_list(data_type) or pa.types.is_large_list(data_type):
        return [data_type.value_field]
    if pa.types.is_fixed_size_list(data_type):
        return [data_type.value_field]
    if pa.types.is_map(data_type):
        return [data_type.key_field, data_type.item_field]
    if pa.types.is_union(data_type):
        return [data_type.field(index) for index in range(data_type.num_fields)]
    return []


def _arrow_field(field: pa.Field) -> dict[str, Any]:
    return {
        "name": field.name,
        "type": str(field.type),
        "nullable": field.nullable,
        "children": [
            _arrow_field(child) for child in _arrow_type_children(field.type)
        ],
        "metadata": _metadata_items(field.metadata),
    }


def _arrow_schema_fields(schema: pa.Schema) -> list[dict[str, Any]]:
    return [_arrow_field(field) for field in schema]


def _parquet_leaf(pf: pq.ParquetFile, index: int) -> dict[str, Any]:
    column = pf.schema.column(index)
    return {
        "index": index,
        "path": column.path,
        "physical_type": column.physical_type,
        "logical_type": str(column.logical_type),
        "converted_type": str(column.converted_type),
        "max_definition_level": column.max_definition_level,
        "max_repetition_level": column.max_repetition_level,
        "length": _json_safe(column.length),
        "precision": _json_safe(column.precision),
        "scale": _json_safe(column.scale),
    }


def _statistics(column: Any) -> dict[str, Any]:
    statistics = column.statistics if column.is_stats_set else None
    unavailable: list[str] = []

    if statistics is None:
        return {
            "reported": False,
            "min_max_available": False,
            "min": None,
            "max": None,
            "null_count_available": False,
            "null_count": None,
            "distinct_count_available": False,
            "distinct_count": None,
            "num_values": None,
            "unavailable": [
                "min",
                "max",
                "null_count",
                "distinct_count",
                "statistics_num_values",
            ],
            "source": "parquet_footer_metadata",
        }

    min_max_available = bool(statistics.has_min_max)
    null_count_available = bool(statistics.has_null_count)
    distinct_count_available = bool(statistics.has_distinct_count)
    if not min_max_available:
        unavailable.extend(("min", "max"))
    if not null_count_available:
        unavailable.append("null_count")
    if not distinct_count_available:
        unavailable.append("distinct_count")

    return {
        "reported": True,
        "min_max_available": min_max_available,
        "min": _json_safe(statistics.min) if min_max_available else None,
        "max": _json_safe(statistics.max) if min_max_available else None,
        "null_count_available": null_count_available,
        "null_count": (
            _json_safe(statistics.null_count) if null_count_available else None
        ),
        "distinct_count_available": distinct_count_available,
        "distinct_count": (
            _json_safe(statistics.distinct_count)
            if distinct_count_available
            else None
        ),
        "num_values": _json_safe(statistics.num_values),
        "unavailable": unavailable,
        "source": "parquet_footer_metadata",
    }


def _column_chunk(column: Any, column_index: int) -> dict[str, Any]:
    statistics = _statistics(column)
    return {
        "column_index": column_index,
        "path_in_schema": column.path_in_schema,
        "physical_type": str(column.physical_type),
        "num_values": column.num_values,
        "compression": str(column.compression),
        "encodings": [str(encoding) for encoding in column.encodings],
        "has_dictionary_page": bool(column.has_dictionary_page),
        "dictionary_page_offset": column.dictionary_page_offset,
        "data_page_offset": column.data_page_offset,
        "file_offset": column.file_offset,
        "compressed_size_bytes": column.total_compressed_size,
        "uncompressed_size_bytes": column.total_uncompressed_size,
        "statistics": statistics,
        "parquet_column_metadata": _metadata_items(
            getattr(column, "metadata", None)
        ),
    }


def _row_groups(pf: pq.ParquetFile) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row_group_index in range(pf.metadata.num_row_groups):
        row_group = pf.metadata.row_group(row_group_index)
        chunks = [
            _column_chunk(row_group.column(column_index), column_index)
            for column_index in range(row_group.num_columns)
        ]
        output.append(
            {
                "index": row_group_index,
                "row_count": row_group.num_rows,
                "column_count": row_group.num_columns,
                "footer_uncompressed_size_bytes": row_group.total_byte_size,
                "sum_column_chunk_compressed_size_bytes": sum(
                    chunk["compressed_size_bytes"] for chunk in chunks
                ),
                "sum_column_chunk_uncompressed_size_bytes": sum(
                    chunk["uncompressed_size_bytes"] for chunk in chunks
                ),
                "sorting_columns": _json_safe(
                    list(getattr(row_group, "sorting_columns", []))
                ),
                "column_chunks": chunks,
            }
        )
    return output


def _summarise_statistics(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(chunks)
    reported = sum(chunk["statistics"]["reported"] for chunk in chunks)
    min_max = sum(
        chunk["statistics"]["min_max_available"] for chunk in chunks
    )
    null_counts = sum(
        chunk["statistics"]["null_count_available"] for chunk in chunks
    )
    distinct_counts = sum(
        chunk["statistics"]["distinct_count_available"] for chunk in chunks
    )

    global_min: Any = None
    global_max: Any = None
    min_max_complete = total > 0 and min_max == total
    if min_max_complete:
        try:
            global_min = _json_safe(
                min(chunk["statistics"]["min"] for chunk in chunks)
            )
            global_max = _json_safe(
                max(chunk["statistics"]["max"] for chunk in chunks)
            )
        except (TypeError, ValueError):
            min_max_complete = False
            global_min = None
            global_max = None

    null_count_total: int | None = None
    null_count_total_available = total > 0 and null_counts == total
    if null_count_total_available:
        null_count_total = sum(
            int(chunk["statistics"]["null_count"]) for chunk in chunks
        )

    return {
        "column_chunks": total,
        "statistics_reported": reported,
        "min_max_reported": min_max,
        "global_min_max_complete": min_max_complete,
        "global_min": global_min,
        "global_max": global_max,
        "null_count_reported": null_counts,
        "null_count_total_available": null_count_total_available,
        "null_count_total": null_count_total,
        "distinct_count_reported": distinct_counts,
        "sum_compressed_size_bytes": sum(
            chunk["compressed_size_bytes"] for chunk in chunks
        ),
        "sum_uncompressed_size_bytes": sum(
            chunk["uncompressed_size_bytes"] for chunk in chunks
        ),
    }


def _dictionary_type_family(value: str) -> str | None:
    normalised = value.strip().lower()
    if "string" in normalised:
        return "string"
    if "date" in normalised:
        return "date"
    if "float" in normalised or "double" in normalised:
        return "float"
    if "int" in normalised:
        return "integer"
    return None


def _arrow_type_family(arrow_type: pa.DataType) -> str:
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_date(arrow_type) or pa.types.is_timestamp(arrow_type):
        return "date"
    if pa.types.is_floating(arrow_type):
        return "float"
    if pa.types.is_integer(arrow_type):
        return "integer"
    return str(arrow_type)


def _column_records(
    pf: pq.ParquetFile,
    dictionary_table: DictionaryTable | None,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    leaves = [_parquet_leaf(pf, index) for index in range(len(pf.schema))]
    chunks_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_path[chunk["path_in_schema"]].append(chunk)

    output: list[dict[str, Any]] = []
    for index, field in enumerate(pf.schema_arrow):
        prefixes = (field.name + ".",)
        field_leaves = [
            leaf
            for leaf in leaves
            if leaf["path"] == field.name or leaf["path"].startswith(prefixes)
        ]
        field_chunks = [
            chunk
            for path in (leaf["path"] for leaf in field_leaves)
            for chunk in chunks_by_path.get(path, [])
        ]
        documented = (
            dictionary_table.fields.get(field.name)
            if dictionary_table is not None
            else None
        )
        type_compatible: bool | None = None
        if documented is not None:
            expected = _dictionary_type_family(documented.declared_type)
            actual = _arrow_type_family(field.type)
            type_compatible = expected is None or expected == actual
        statistics_summary = _summarise_statistics(field_chunks)

        output.append(
            {
                "index": index,
                "name": field.name,
                "arrow_type": str(field.type),
                "arrow_type_family": _arrow_type_family(field.type),
                "nullable": field.nullable,
                "field_metadata": _metadata_items(field.metadata),
                "parquet_leaves": field_leaves,
                "dictionary_declared_type": (
                    documented.declared_type if documented is not None else None
                ),
                "dictionary_description": (
                    documented.description if documented is not None else None
                ),
                "dictionary_type_compatible": type_compatible,
                "statistics_summary": statistics_summary,
                "metadata_observations": (
                    [
                        (
                            "All reported row-group min/max statistics contain "
                            "the same non-null value: "
                            f"{statistics_summary['global_min']}"
                        )
                    ]
                    if (
                        field_chunks
                        and statistics_summary["global_min_max_complete"]
                        and statistics_summary["global_min"]
                        == statistics_summary["global_max"]
                        and statistics_summary["null_count_total_available"]
                    )
                    else []
                ),
            }
        )
    return output


def _candidate_keys(
    table_name: str,
    columns: list[dict[str, Any]],
    dictionary_tables: dict[str, DictionaryTable],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    identifiers: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    customers = dictionary_tables.get("customers")
    customer_id = customers.fields.get("client_id") if customers else None

    for column in columns:
        description = column["dictionary_description"] or ""
        lower = description.lower()
        summary = column["statistics_summary"]
        metadata_observation = {
            "null_count_total_available": summary["null_count_total_available"],
            "null_count_total": summary["null_count_total"],
            "distinct_count_reported_chunks": summary[
                "distinct_count_reported"
            ],
            "limitation": (
                "Footer metadata is insufficient to verify uniqueness or "
                "referential integrity."
            ),
        }

        unique_identifier = re.search(
            r"\bunique(?:\s+[a-z-]+){0,2}\s+identifier\b", lower
        )
        if unique_identifier:
            identifiers.append(
                {
                    "table": table_name,
                    "column": column["name"],
                    "role": "unique_identifier_candidate",
                    "verified": False,
                    "evidence": [f"Dictionary description: {description}"],
                    "metadata_observations": metadata_observation,
                }
            )

        if "join" in lower:
            target_match = re.search(
                r"\bjoins?\s+to\s+([A-Za-z_][A-Za-z0-9_]*)"
                r"\.([A-Za-z_][A-Za-z0-9_]*)",
                description,
                re.IGNORECASE,
            )
            relationships.append(
                {
                    "source_table": table_name,
                    "source_column": column["name"],
                    "target_table": (
                        target_match.group(1) if target_match else None
                    ),
                    "target_column": (
                        target_match.group(2) if target_match else None
                    ),
                    "role": (
                        "foreign_key_candidate"
                        if target_match
                        else "join_field_candidate"
                    ),
                    "verified": False,
                    "evidence": [f"Dictionary description: {description}"],
                    "metadata_observations": metadata_observation,
                }
            )

        has_customer_relationship = any(
            relationship["source_column"] == column["name"]
            and relationship["target_table"] == "customers"
            for relationship in relationships
        )
        if (
            column["name"] == "client_id_fk"
            and customer_id is not None
            and not has_customer_relationship
        ):
            relationships.append(
                {
                    "source_table": table_name,
                    "source_column": column["name"],
                    "target_table": "customers",
                    "target_column": "client_id",
                    "role": "foreign_key_candidate",
                    "verified": False,
                    "evidence": [
                        f"Dictionary description: {description}",
                        (
                            "The customers.client_id description identifies it "
                            f"as a join key: {customer_id.description}"
                        ),
                        "The exact client_id_fk column exists in the actual schema.",
                    ],
                    "metadata_observations": metadata_observation,
                }
            )

    return identifiers, relationships


def _reconciliation(
    table_name: str,
    actual_rows: int,
    columns: list[dict[str, Any]],
    dictionary_table: DictionaryTable | None,
) -> dict[str, Any]:
    documented_fields = dictionary_table.fields if dictionary_table else {}
    actual_names = {column["name"] for column in columns}
    missing_fields = sorted(set(documented_fields) - actual_names)
    undocumented_fields = sorted(actual_names - set(documented_fields))
    type_mismatches = [
        {
            "column": column["name"],
            "dictionary_type": column["dictionary_declared_type"],
            "arrow_type": column["arrow_type"],
            "comparison": "coarse type families differ",
        }
        for column in columns
        if column["dictionary_type_compatible"] is False
    ]
    documented_rows = (
        dictionary_table.documented_rows if dictionary_table is not None else None
    )

    return {
        "dictionary_table_matched": dictionary_table is not None,
        "documented_row_count": documented_rows,
        "actual_row_count": actual_rows,
        "row_count_matches": (
            documented_rows == actual_rows if documented_rows is not None else None
        ),
        "documented_fields_missing_from_schema": missing_fields,
        "schema_fields_absent_from_dictionary": undocumented_fields,
        "dictionary_type_mismatches": type_mismatches,
    }


def _relevance(
    table_name: str, columns: list[dict[str, Any]]
) -> dict[str, Any]:
    column_names = {column["name"] for column in columns}
    if table_name == "transactions":
        supporting_fields = sorted(
            column_names & {"book_date", "amount_eur", "dc_indicator"}
        )
        return {
            "classification": "direct_candidate",
            "assessment": (
                "The dictionary describes individual financial events, and the "
                "actual footer schema contains fields plausibly relevant to "
                "weekly bank-transaction cash flow."
            ),
            "metadata_evidence": supporting_fields,
            "status": "preliminary_unverified",
            "limitations": [
                "Field presence does not establish data quality, sign semantics, "
                "SME coverage, or weekly completeness.",
            ],
        }
    if table_name == "customers":
        supporting_fields = sorted(column_names & {"client_id", "segment"})
        segment = next(
            (column for column in columns if column["name"] == "segment"), None
        )
        segment_summary = segment["statistics_summary"] if segment else None
        segment_observation = []
        if (
            segment_summary
            and segment_summary["global_min_max_complete"]
            and segment_summary["global_min"] == "Private"
            and segment_summary["global_max"] == "Private"
        ):
            segment_observation.append(
                "Complete reported row-group min/max statistics identify only "
                "the value Private for segment. This may indicate that the "
                "extracted customer table contains no SME rows, but Task 2C "
                "must verify the segment distribution."
            )
        return {
            "classification": "cohort_selection_support",
            "assessment": (
                "The dictionary describes customer segment information, which "
                "would be needed to identify the simulated SME cohort in a later "
                "stage."
            ),
            "metadata_evidence": supporting_fields,
            "status": "preliminary_unverified",
            "metadata_observations": segment_observation,
            "limitations": [
                "The distribution and completeness of segment codes require "
                "record-level verification.",
            ],
        }
    if table_name in {
        "leasing_agreements",
        "life_insurance",
        "property_insurance",
        "pension",
        "margin_assets",
        "margin_liabilities",
    }:
        return {
            "classification": "contextual_only",
            "assessment": (
                "The dictionary describes product or balance snapshots. These "
                "may provide contextual features, but this metadata does not "
                "establish cash-flow relevance or predictive value."
            ),
            "metadata_evidence": sorted(column_names),
            "status": "preliminary_unverified",
            "limitations": [
                "Snapshot timing, coverage, and alignment with weekly transaction "
                "flow require separate validation.",
            ],
        }
    return {
        "classification": "unassessed",
        "assessment": "No preliminary relevance category was assigned.",
        "metadata_evidence": sorted(column_names),
        "status": "preliminary_unverified",
        "limitations": ["Table role and schema require manual review."],
    }


def inspect_parquet_file(
    path: Path,
    dictionary_tables: dict[str, DictionaryTable],
) -> dict[str, Any]:
    """Build a metadata-only report record for one Parquet file."""

    parquet_file = pq.ParquetFile(path)
    metadata = parquet_file.metadata
    dictionary_table = dictionary_tables.get(path.stem)
    row_groups = _row_groups(parquet_file)
    all_chunks = [
        chunk for row_group in row_groups for chunk in row_group["column_chunks"]
    ]
    columns = _column_records(parquet_file, dictionary_table, all_chunks)
    identifiers, relationships = _candidate_keys(
        path.stem, columns, dictionary_tables
    )
    reconciliation = _reconciliation(
        path.stem, metadata.num_rows, columns, dictionary_table
    )

    return {
        "file_name": path.name,
        "table_name": path.stem,
        "file_size_bytes": path.stat().st_size,
        "parquet_metadata": {
            "format_version": metadata.format_version,
            "created_by": metadata.created_by,
            "serialized_footer_size_bytes": metadata.serialized_size,
            "row_count": metadata.num_rows,
            "row_group_count": metadata.num_row_groups,
            "column_count_arrow_top_level": len(parquet_file.schema_arrow),
            "column_count_parquet_leaves": len(parquet_file.schema),
            "file_metadata": _metadata_items(metadata.metadata),
        },
        "arrow_schema": _arrow_schema_fields(parquet_file.schema_arrow),
        "parquet_schema": [
            _parquet_leaf(parquet_file, index)
            for index in range(len(parquet_file.schema))
        ],
        "columns": columns,
        "row_groups": row_groups,
        "dictionary": {
            "matched_by_table_name": dictionary_table is not None,
            "purpose": (
                dictionary_table.purpose if dictionary_table is not None else None
            ),
            "documented_fields": (
                {
                    name: {
                        "declared_type": field.declared_type,
                        "description": field.description,
                    }
                    for name, field in dictionary_table.fields.items()
                }
                if dictionary_table is not None
                else {}
            ),
        },
        "reconciliation": reconciliation,
        "candidate_identifiers": identifiers,
        "relationship_candidates": relationships,
        "relevance": _relevance(
            path.stem, columns
        ),
        "limitations": [
            "All findings come from Parquet footer metadata and the local data "
            "dictionary; no records were scanned.",
            "Column statistics may be absent, truncated, or unsuitable for "
            "verifying uniqueness and referential integrity.",
            "Dictionary claims are not treated as verified schema relationships.",
        ],
    }


def inspect_dataset(
    dataset_dir: Path, dictionary_path: Path
) -> dict[str, Any]:
    """Inspect every Parquet file in a dataset directory."""

    if not dataset_dir.is_dir():
        raise ValueError(f"Dataset directory not found: {dataset_dir.name}")
    if not dictionary_path.is_file():
        raise ValueError(f"Dictionary file not found: {dictionary_path.name}")

    parquet_paths = sorted(
        path for path in dataset_dir.glob("*.parquet") if path.is_file()
    )
    if not parquet_paths:
        raise ValueError("No Parquet files found in the dataset directory")

    dictionary_tables = parse_dictionary(dictionary_path)
    files = [
        inspect_parquet_file(path, dictionary_tables) for path in parquet_paths
    ]
    return {
        "report_schema_version": "1.0",
        "inspection_mode": "metadata_only",
        "reader": "pyarrow.parquet.ParquetFile",
        "pyarrow_version": pa.__version__,
        "dataset_name": dataset_dir.name,
        "dictionary_file": {
            "file_name": dictionary_path.name,
            "file_size_bytes": dictionary_path.stat().st_size,
            "table_count": len(dictionary_tables),
        },
        "summary": {
            "parquet_file_count": len(files),
            "total_file_size_bytes": sum(item["file_size_bytes"] for item in files),
            "total_rows": sum(
                item["parquet_metadata"]["row_count"] for item in files
            ),
            "total_row_groups": sum(
                item["parquet_metadata"]["row_group_count"] for item in files
            ),
        },
        "files": files,
        "global_limitations": [
            "No Parquet table, row group, or column values were loaded.",
            "SME eligibility, uniqueness, joins, temporal continuity and "
            "cash-flow semantics remain unverified.",
            "Record-level profiling must be a separate Task 2C activity.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    if value is None:
        return "—"
    return (
        str(value)
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "\\|")
    )


def _format_bytes(value: int) -> str:
    return f"{value:,}"


def _format_stat_value(
    summary: dict[str, Any], key: str, available_key: str
) -> str:
    if not summary[available_key]:
        return "Unavailable"
    return _markdown_cell(summary[key])


def render_markdown(report: dict[str, Any]) -> str:
    """Render the academic review report from the structured inventory."""

    summary = report["summary"]
    lines = [
        "# CashFlowAI Parquet Metadata Inventory",
        "",
        "This report was generated from Parquet footer metadata and the local "
        "HTML data dictionary. It does not contain table records and does not "
        "verify data quality or relationships.",
        "",
        "## Dataset Summary",
        "",
        "| Property | Value |",
        "| --- | ---: |",
        f"| Parquet files | {summary['parquet_file_count']} |",
        f"| Total file size (bytes) | {_format_bytes(summary['total_file_size_bytes'])} |",
        f"| Total metadata rows | {_format_bytes(summary['total_rows'])} |",
        f"| Total row groups | {_format_bytes(summary['total_row_groups'])} |",
        f"| PyArrow version | {_markdown_cell(report['pyarrow_version'])} |",
        "",
        "## Table Overview",
        "",
        "| Table | Purpose | Rows | Row groups | File size (bytes) |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for item in report["files"]:
        purpose = item["dictionary"]["purpose"] or "Not documented"
        lines.append(
            f"| {_markdown_cell(item['table_name'])} | "
            f"{_markdown_cell(purpose)} | "
            f"{item['parquet_metadata']['row_count']:,} | "
            f"{item['parquet_metadata']['row_group_count']} | "
            f"{item['file_size_bytes']:,} |"
        )

    lines.extend(
        [
            "",
            "## Key and Relationship Candidates",
            "",
            "All candidates below are unverified. Footer metadata cannot prove "
            "global uniqueness or referential integrity.",
            "",
        ]
    )
    candidates: list[dict[str, Any]] = []
    for item in report["files"]:
        candidates.extend(item["candidate_identifiers"])
        candidates.extend(item["relationship_candidates"])
    if candidates:
        lines.extend(
            [
                "| Source | Role | Target | Status |",
                "| --- | --- | --- | --- |",
            ]
        )
        for candidate in candidates:
            if "source_column" in candidate:
                source = (
                    f"{candidate['source_table']}.{candidate['source_column']}"
                )
                role = candidate["role"]
                target = (
                    f"{candidate['target_table']}.{candidate['target_column']}"
                    if candidate["target_table"]
                    else "Not specified"
                )
            else:
                source = f"{candidate['table']}.{candidate['column']}"
                role = candidate["role"]
                target = "—"
            lines.append(
                f"| {_markdown_cell(source)} | {_markdown_cell(role)} | "
                f"{_markdown_cell(target)} | Unverified |"
            )
    else:
        lines.append("No documented identifier or join candidates were found.")

    for item in report["files"]:
        metadata = item["parquet_metadata"]
        rows = metadata["row_count"]
        row_group_rows = [group["row_count"] for group in item["row_groups"]]
        compressed = sum(
            group["sum_column_chunk_compressed_size_bytes"]
            for group in item["row_groups"]
        )
        uncompressed = sum(
            group["sum_column_chunk_uncompressed_size_bytes"]
            for group in item["row_groups"]
        )
        reconciliation = item["reconciliation"]
        lines.extend(
            [
                "",
                f"## Table: `{item['table_name']}`",
                "",
                "### Purpose",
                "",
                item["dictionary"]["purpose"] or "Not documented by the data dictionary.",
                "",
                "### Verified Parquet Metadata",
                "",
                f"- File: `{item['file_name']}`",
                f"- File size: {item['file_size_bytes']:,} bytes",
                f"- Actual rows: {rows:,}",
                f"- Row groups: {metadata['row_group_count']}",
                f"- Row-group row-count range: {min(row_group_rows):,}–"
                f"{max(row_group_rows):,}",
                f"- Column-chunk compressed total: {compressed:,} bytes",
                f"- Column-chunk uncompressed total: {uncompressed:,} bytes",
                f"- Parquet writer: {_markdown_cell(metadata['created_by'])}",
                f"- Parquet format version: {_markdown_cell(metadata['format_version'])}",
                "",
                "### Column Inventory",
                "",
                "| Column | Arrow type | Parquet physical type | Logical type | "
                "Nullable | Dictionary description | Statistics | "
                "Null count (metadata) | Metadata min–max |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for column in item["columns"]:
            leaves = column["parquet_leaves"]
            physical = ", ".join(leaf["physical_type"] for leaf in leaves)
            logical = ", ".join(leaf["logical_type"] for leaf in leaves)
            stats = column["statistics_summary"]
            if stats["column_chunks"]:
                stats_text = (
                    f"{stats['statistics_reported']}/{stats['column_chunks']} "
                    f"chunks; min/max "
                    f"{stats['min_max_reported']}/{stats['column_chunks']}"
                )
                if stats["null_count_total_available"]:
                    null_count = f"{stats['null_count_total']:,}"
                elif stats["null_count_reported"]:
                    null_count = (
                        f"Incomplete ({stats['null_count_reported']}/"
                        f"{stats['column_chunks']} chunks)"
                    )
                else:
                    null_count = "Unavailable"
                if stats["global_min_max_complete"]:
                    minimum = _markdown_cell(stats["global_min"])
                    maximum = _markdown_cell(stats["global_max"])
                    min_max = f"{minimum} — {maximum}"
                else:
                    min_max = "Unavailable or incomplete"
            else:
                stats_text = "No matching chunks"
                null_count = "Unavailable"
                min_max = "Unavailable"
            lines.append(
                f"| {_markdown_cell(column['name'])} | "
                f"{_markdown_cell(column['arrow_type'])} | "
                f"{_markdown_cell(physical)} | {_markdown_cell(logical)} | "
                f"{column['nullable']} | "
                f"{_markdown_cell(column['dictionary_description'])} | "
                f"{stats_text} | {null_count} | {min_max} |"
            )

        observations = [
            f"`{column['name']}`: {observation}"
            for column in item["columns"]
            for observation in column["metadata_observations"]
        ]
        if observations:
            lines.extend(
                [
                    "",
                    "Metadata observations requiring record-level confirmation:",
                    "",
                ]
            )
            lines.extend(f"- {observation}" for observation in observations)

        lines.extend(
            [
                "",
                "### Identifiers and Join Fields",
                "",
            ]
        )
        item_candidates = item["candidate_identifiers"] + item[
            "relationship_candidates"
        ]
        if item_candidates:
            for candidate in item_candidates:
                column = candidate.get("column") or candidate.get("source_column")
                target = (
                    f" → {candidate.get('target_table')}."
                    f"{candidate.get('target_column')}"
                    if candidate.get("target_table")
                    else ""
                )
                evidence = "; ".join(candidate["evidence"])
                lines.append(
                    f"- `{column}` — {candidate['role']}{target}. "
                    f"Unverified. Evidence: {evidence}"
                )
        else:
            lines.append("No documented key or join candidate identified.")

        lines.extend(
            [
                "",
                "### Schema and Dictionary Reconciliation",
                "",
                f"- Dictionary table matched: "
                f"{reconciliation['dictionary_table_matched']}",
                f"- Dictionary row count: "
                f"{reconciliation['documented_row_count']:,}"
                if reconciliation["documented_row_count"] is not None
                else "- Dictionary row count: Not documented",
                f"- Actual row count: {reconciliation['actual_row_count']:,}",
                f"- Row counts match: "
                f"{reconciliation['row_count_matches']}",
                "- Documented fields absent from schema: "
                + (
                    ", ".join(
                        f"`{name}`"
                        for name in reconciliation[
                            "documented_fields_missing_from_schema"
                        ]
                    )
                    or "None"
                ),
                "- Schema fields absent from dictionary: "
                + (
                    ", ".join(
                        f"`{name}`"
                        for name in reconciliation[
                            "schema_fields_absent_from_dictionary"
                        ]
                    )
                    or "None"
                ),
            ]
        )
        type_mismatches = reconciliation["dictionary_type_mismatches"]
        if type_mismatches:
            lines.append("- Coarse type-family mismatches:")
            for mismatch in type_mismatches:
                lines.append(
                    f"  - `{mismatch['column']}`: dictionary "
                    f"`{mismatch['dictionary_type']}` vs Arrow "
                    f"`{mismatch['arrow_type']}`"
                )
        else:
            lines.append("- Coarse type-family mismatches: None")

        relevance = item["relevance"]
        lines.extend(
            [
                "",
                "### Relevance to SME Cash-Flow Forecasting",
                "",
                f"- Classification: `{relevance['classification']}`",
                f"- Assessment: {relevance['assessment']}",
                f"- Status: `{relevance['status']}`",
                "- Limitations: " + " ".join(relevance["limitations"]),
                *(
                    f"- Observation: {observation}"
                    for observation in relevance.get(
                        "metadata_observations", []
                    )
                ),
                "",
                "### Record-Level Verification Required",
                "",
                "- Statistics cannot prove global uniqueness or foreign-key validity.",
                "- Null counts and min/max values are reported only where the "
                "Parquet footer provides them.",
                "- Value domains, temporal continuity, SME eligibility and "
                "cash-flow semantics require Task 2C profiling.",
                "- Data-dictionary claims remain distinct from verified Parquet "
                "metadata.",
            ]
        )

    lines.extend(
        [
            "",
            "## Global Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["global_limitations"])
    lines.extend(
        [
            "",
            "Detailed row-group and column-chunk metadata is retained in "
            "`parquet_inventory.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def summarise_report(report: dict[str, Any]) -> dict[str, Any]:
    """Create a compact structured report without repeating chunk statistics."""

    summary = {
        key: value
        for key, value in report.items()
        if key != "files"
    }
    summary["report_kind"] = "compact_summary"
    summary["full_detail_note"] = (
        "Detailed row-group and column-chunk statistics are retained in the "
        "regenerable local parquet_inventory.json report."
    )

    files: list[dict[str, Any]] = []
    for item in report["files"]:
        row_groups = item["row_groups"]
        chunks = [
            chunk for row_group in row_groups for chunk in row_group["column_chunks"]
        ]
        compact_item = {
            key: item[key]
            for key in (
                "file_name",
                "table_name",
                "file_size_bytes",
                "parquet_metadata",
                "arrow_schema",
                "parquet_schema",
                "columns",
                "dictionary",
                "reconciliation",
                "candidate_identifiers",
                "relationship_candidates",
                "relevance",
                "limitations",
            )
        }
        compact_item["row_group_summary"] = {
            "row_group_count": len(row_groups),
            "row_count_min": min(
                (row_group["row_count"] for row_group in row_groups),
                default=None,
            ),
            "row_count_max": max(
                (row_group["row_count"] for row_group in row_groups),
                default=None,
            ),
            "column_chunk_count": len(chunks),
            "column_chunks_with_statistics": sum(
                chunk["statistics"]["reported"] for chunk in chunks
            ),
            "column_chunks_with_min_max": sum(
                chunk["statistics"]["min_max_available"] for chunk in chunks
            ),
            "sum_column_chunk_compressed_size_bytes": sum(
                chunk["compressed_size_bytes"] for chunk in chunks
            ),
            "sum_column_chunk_uncompressed_size_bytes": sum(
                chunk["uncompressed_size_bytes"] for chunk in chunks
            ),
        }
        files.append(compact_item)

    summary["files"] = files
    return summary


def write_reports(
    report: dict[str, Any],
    json_path: Path,
    markdown_path: Path,
    summary_json_path: Path,
) -> None:
    """Write deterministic UTF-8 full, summary and Markdown reports."""

    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    json_path.write_text(json_text + "\n", encoding="utf-8", newline="\n")
    summary = summarise_report(report)
    summary_text = json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    summary_json_path.write_text(
        summary_text + "\n", encoding="utf-8", newline="\n"
    )
    markdown_path.write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect Parquet footer metadata and reconcile it with the local "
            "HTML data dictionary without loading table records."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DATASET_DIR,
        help=f"Extracted dataset directory (default: {DATASET_DIR.as_posix()})",
    )
    parser.add_argument(
        "--dictionary",
        type=Path,
        default=DICTIONARY_PATH,
        help=f"Data dictionary path (default: {DICTIONARY_PATH.as_posix()})",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=JSON_REPORT,
        help=f"JSON report path (default: {JSON_REPORT.as_posix()})",
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=MARKDOWN_REPORT,
        help=f"Markdown report path (default: {MARKDOWN_REPORT.as_posix()})",
    )
    parser.add_argument(
        "--summary-json-report",
        type=Path,
        default=SUMMARY_JSON_REPORT,
        help=(
            "Compact JSON report path "
            f"(default: {SUMMARY_JSON_REPORT.as_posix()})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        dataset = args.dataset_dir.resolve()
        for report_path in (
            args.json_report,
            args.markdown_report,
            args.summary_json_report,
        ):
            if report_path.resolve().is_relative_to(dataset):
                raise ValueError("Report output must be outside the source dataset")

        report = inspect_dataset(args.dataset_dir, args.dictionary)
        write_reports(
            report,
            args.json_report,
            args.markdown_report,
            args.summary_json_report,
        )
    except (OSError, ValueError, pa.ArrowException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = report["summary"]
    print(f"Parquet files: {summary['parquet_file_count']}")
    print(f"Total rows: {summary['total_rows']}")
    print(f"Row groups: {summary['total_row_groups']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
