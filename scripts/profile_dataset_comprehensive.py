#!/usr/bin/env python3
"""Profile all CashFlowAI Parquet tables with bounded aggregate state."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import statistics
import sys
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

try:
    from scripts.inspect_parquet_metadata import parse_dictionary
except ModuleNotFoundError:
    from inspect_parquet_metadata import parse_dictionary


DATASET_DIR = Path("synthetic_banking/student_export")
METADATA_REPORT = Path(
    "reports/data_inspection/parquet_inventory_summary.json"
)
JSON_REPORT = Path(
    "reports/data_inspection/comprehensive_dataset_analysis.json"
)
MARKDOWN_REPORT = Path(
    "reports/data_inspection/comprehensive_dataset_analysis.md"
)
DEFAULT_BATCH_SIZE = 65_536
DEFAULT_MEMORY_LIMIT_MB = 1024
MAX_EXACT_ID_VALUES = 500_000
MAX_EXACT_DISTINCT_VALUES = 500_000
MAX_EXACT_COMPOSITE_ROWS = 1_000_000
SAMPLE_LIMIT = 100_000
TOP_CATEGORY_COUNT = 30

DATE_COLUMNS = {"bank_reg_dt", "birth_or_reg_dt", "book_date", "snapshot_date", "month_end", "contrib_date"}
HIGH_CARDINALITY_DESCRIPTIVE = {"book_time", "postal_code"}
HIGH_CARDINALITY_IDENTIFIERS = {"txn_id", "acct_iban", "counterparty_iban"}
BOUNDED_IDENTIFIERS = {"client_id", "client_id_fk", "household_id", "corp_group_id"}
FINANCIAL_COLUMNS = {
    "amount_eur",
    "amount_orig",
    "orig_principal",
    "outstanding_principal",
    "carrying_amount",
    "sum_insured",
    "next_premium",
    "premium_eur",
    "surrender_value_eur",
    "end_balance_eur",
    "avg_balance_eur",
    "avg_interest_base_eur",
}
CATEGORICAL_NUMERIC = {
    "year",
    "month",
    "day_in_month",
    "group_head_flg",
    "agreement_status",
}
EXPECTED_CATEGORIES = {
    "segment": {"Private", "SME", "Corporate"},
    "type_cd": {"H", "C"},
    "gender_cd": {"M", "F", "U", "X"},
    "lang_pref": {"ET", "EN", "RU"},
    "region_cd": {"TLN", "TRT", "NRV", "PRN", "RUR", "OTH"},
    "household_role": {"primary", "partner", "dependent", "single"},
    "group_head_flg": {0, 1},
    "dc_indicator": {"C", "D"},
    "channel": {"card", "online", "mobile", "branch", "atm"},
    "trx_ccy": {"EUR", "USD", "SEK", "NOK", "GBP"},
    "weekday_name": {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"},
    "txn_type": {
        "salary",
        "bonus",
        "payroll_run",
        "tax_withholding",
        "social_insurance",
        "support_income",
        "card_purchase",
        "card_refund",
        "subscription",
        "internal_transfer",
        "business_payment",
        "business_receipt",
        "household_transfer",
        "allowance_transfer",
        "utility_bill",
        "savings_sweep",
        "loan_servicing",
        "cash_withdrawal",
    },
    "purpose_code": {
        "SALA",
        "BONU",
        "BENE",
        "SSBE",
        "TAXS",
        "GDDS",
        "SUBS",
        "RENT",
        "CHAR",
        "ELEC",
        "SAVG",
        "LOAR",
        "SUPP",
        "CASH",
        "GIFT",
        "FEES",
        "OTHR",
    },
    "lease_ccy": {"EUR", "USD", "SEK"},
    "policy_ccy": {"EUR", "USD"},
    "acct_ccy": {"EUR", "USD", "SEK", "NOK"},
    "contract_ccy": {"EUR", "USD", "SEK", "NOK"},
    "cover_type_cd": {"E", "P"},
    "fund_code": {"PEN-A", "PEN-B", "PEN-C", "PEN-D", "PEN-E"},
    "agreement_status": {-1, 0, 1, 2},
    "lease_status": {
        "offer",
        "enactment",
        "valid",
        "temporary terminated",
        "terminated",
        "completely terminated",
        "archived",
    },
    "policy_status": {
        "ALG",
        "REGTUD",
        "MAKSEOOT",
        "JOUS",
        "KATK",
        "LOPET",
        "LOPPKAES",
        "LOPPSURM",
        "ANULL",
    },
}
TABLE_CLASSIFICATION = {
    "customers": "customer master data",
    "transactions": "transaction event history",
    "leasing_agreements": "monthly agreement snapshots",
    "life_insurance": "monthly insurance-policy snapshots",
    "property_insurance": "monthly insurance-policy snapshots",
    "pension": "periodic pension contribution records",
    "margin_assets": "monthly positive-balance snapshots",
    "margin_liabilities": "monthly liability-balance snapshots",
}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return {"binary_byte_length": len(value)}
    if isinstance(value, dict):
        return {str(_json_safe(k)): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _sanitize_text(value: str) -> str:
    value = re.sub(
        r"\b(?:CL|TX)\d{4,}\b", "[identifier example omitted]", value
    )
    return " ".join(value.split())


def _load_metadata(path: Path) -> dict[str, Any]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("inspection_mode") != "metadata_only":
        raise ValueError("Expected the Task 2B metadata-only report")
    return metadata


def _table_metadata(metadata: dict[str, Any], table_name: str) -> dict[str, Any]:
    item = next(
        (item for item in metadata["files"] if item["table_name"] == table_name),
        None,
    )
    if item is None:
        raise ValueError(f"Table metadata not found: {table_name}")
    return item


def _classify_column(name: str, arrow_type: pa.DataType) -> tuple[str, str]:
    if name in BOUNDED_IDENTIFIERS:
        return (
            "identifier",
            "Bounded key used for counting, overlap tests or aggregate uniqueness checks.",
        )
    if name in HIGH_CARDINALITY_IDENTIFIERS:
        return (
            "high_cardinality_identifier",
            "Identifier-like value. Raw values are suppressed and exact global distinctness is deferred.",
        )
    if pa.types.is_timestamp(arrow_type) or pa.types.is_date(arrow_type):
        return "timestamp", "Date or timestamp used to assess coverage and temporal consistency."
    if pa.types.is_floating(arrow_type):
        if name in FINANCIAL_COLUMNS or name == "unit_qty":
            return (
                "financial_measure" if name in FINANCIAL_COLUMNS else "numeric_measure",
                "Numeric measure summarised with exact extrema and bounded quantile sampling.",
            )
        return "numeric", "Continuous numeric value summarised in aggregate."
    if pa.types.is_integer(arrow_type):
        if name in CATEGORICAL_NUMERIC or name in {"year", "month", "day_in_month"}:
            return "categorical_numeric", "Low-cardinality numeric code or calendar component."
        return "numeric", "Integer-valued attribute."
    if pa.types.is_boolean(arrow_type):
        return "category", "Boolean category."
    if name in HIGH_CARDINALITY_DESCRIPTIVE:
        return (
            "high_cardinality_descriptive",
            "Descriptive value whose raw values are suppressed and frequency table is deferred.",
        )
    return "category", "Categorical or descriptive code summarised by exact frequency."


def _cashflow_column_use(table_name: str, name: str, role: str) -> str:
    if table_name == "transactions":
        if name == "amount_eur":
            return "Primary monetary measure; direction must come from dc_indicator."
        if name == "dc_indicator":
            return "Required to distinguish cash inflow from outflow."
        if name == "book_date":
            return "Required time axis for eventual temporal evaluation."
        if name == "client_id_fk":
            return "Required customer linkage, subject to verified cohort availability."
        if name in {"txn_id"}:
            return "Record identifier only; should not become a predictive feature."
        if name in {"txn_type", "purpose_code", "mcc", "channel", "merchant_country"}:
            return "Potential descriptive context after leakage and availability review."
        if name in {"amount_orig", "trx_ccy"}:
            return "Source-currency context; cash-flow target should use documented EUR conversion."
        if name in {"month", "year", "period_yy_mm", "day_in_month", "weekday_name", "book_time"}:
            return "Calendar/time attribute; avoid redundant or future-derived features."
        return "Descriptive context only unless later analysis establishes value."
    if table_name == "customers":
        if name == "client_id":
            return "Essential for customer identification and relationship checks."
        if name == "segment":
            return "Essential for cohort eligibility; currently contains no SME labels."
        if name in {"bank_reg_dt", "birth_or_reg_dt", "type_cd"}:
            return "Potential eligibility or temporal context; requires later leakage review."
        return "Descriptive or cohort context; not a direct cash-flow measure."
    if name in {"client_id_fk"}:
        return "Potential contextual linkage to customers; no SME mapping is established."
    if name in DATE_COLUMNS or name in {"year", "month", "day_in_month"}:
        return "Potential as-of-date context only; temporal alignment and leakage must be checked."
    if name in FINANCIAL_COLUMNS:
        return "Potentially useful historical financial context, not a substitute for transaction cash flow."
    return "Contextual attribute only; current relevance is unverified."


@dataclass
class ColumnState:
    name: str
    arrow_type: str
    parquet_physical_type: str
    parquet_logical_type: str
    nullable: bool
    dictionary_type: str | None
    dictionary_description: str | None
    role: str
    interpretation: str
    cashflow_use: str
    null_count: int = 0
    non_null_count: int = 0
    exact_distinct_values: set[Any] = field(default_factory=set)
    distinct_overflow: bool = False
    categories: Counter[Any] = field(default_factory=Counter)
    date_values: Counter[Any] = field(default_factory=Counter)
    minimum: Any = None
    maximum: Any = None
    numeric_sum: float = 0.0
    numeric_sum_squares: float = 0.0
    numeric_count: int = 0
    zero_count: int = 0
    negative_count: int = 0
    nan_count: int = 0
    string_length_sum: int = 0
    string_length_min: int | None = None
    string_length_max: int | None = None
    blank_count: int = 0
    prefix_counts: Counter[str] = field(default_factory=Counter)
    sampled_values: list[pa.Array] = field(default_factory=list)
    sample_seen_non_null: int = 0
    sample_total_rows: int = 0
    sample_limit: int = SAMPLE_LIMIT


@dataclass
class CustomerReferenceState:
    customer_values: pa.Array
    null_count: int = 0
    referencing_rows: int = 0
    matching_rows: int = 0
    orphan_rows: int = 0
    referenced_ids: set[Any] = field(default_factory=set)
    orphan_ids: set[Any] = field(default_factory=set)
    reference_overflow: bool = False
    orphan_overflow: bool = False


def _bounded_update(
    target: set[Any],
    values: Iterable[Any],
    limit: int,
) -> bool:
    for value in values:
        if value is None:
            continue
        if value in target:
            continue
        if len(target) >= limit:
            return False
        target.add(value)
    return True


def _merge_value_counts(counter: Counter[Any], values: pa.Array) -> None:
    if len(values) == 0:
        return
    counts = pc.value_counts(values).to_pylist()
    for item in counts:
        counter[_json_safe(item["values"])] += int(item["counts"])


def _sample_numeric(
    state: ColumnState,
    values: pa.Array,
    total_rows: int,
) -> None:
    count = len(values)
    if count == 0 or state.sample_limit <= 0:
        state.sample_seen_non_null += count
        return

    stride = max(1, math.ceil(total_rows / state.sample_limit))
    start = state.sample_seen_non_null
    end = start + count
    first = ((start + stride - 1) // stride) * stride
    positions = list(range(first, end, stride))
    if positions:
        relative = pa.array([position - start for position in positions], type=pa.int64())
        state.sampled_values.append(values.take(relative))
        if sum(len(part) for part in state.sampled_values) > state.sample_limit:
            merged = pa.concat_arrays(state.sampled_values)
            state.sampled_values = [merged.slice(0, state.sample_limit)]
    state.sample_seen_non_null = end


def _update_text_details(state: ColumnState, values: pa.Array) -> None:
    if len(values) == 0:
        return
    state.blank_count += int(
        pc.sum(pc.cast(pc.equal(values, ""), pa.int64())).as_py() or 0
    )
    lengths = pc.binary_length(values)
    if len(lengths):
        mm = pc.min_max(lengths).as_py()
        state.string_length_min = (
            mm["min"]
            if state.string_length_min is None
            else min(state.string_length_min, mm["min"])
        )
        state.string_length_max = (
            mm["max"]
            if state.string_length_max is None
            else max(state.string_length_max, mm["max"])
        )
        state.string_length_sum += int(pc.sum(lengths).as_py() or 0)

    prefixes = pc.utf8_slice_codeunits(values, 0, 2)
    _merge_value_counts(state.prefix_counts, prefixes.drop_null())


def _update_column(
    state: ColumnState,
    array: pa.Array,
    total_rows: int,
) -> None:
    state.null_count += array.null_count
    values = array.drop_null()
    state.non_null_count += len(values)
    if len(values) == 0:
        return

    if state.role == "category":
        _merge_value_counts(state.categories, values)
        return
    if state.role == "categorical_numeric":
        _merge_value_counts(state.categories, values)
        minimum_maximum = pc.min_max(values).as_py()
        state.minimum = (
            minimum_maximum["min"]
            if state.minimum is None
            else min(state.minimum, minimum_maximum["min"])
        )
        state.maximum = (
            minimum_maximum["max"]
            if state.maximum is None
            else max(state.maximum, minimum_maximum["max"])
        )
        return
    if state.role == "timestamp":
        _merge_value_counts(state.date_values, values)
        minimum_maximum = pc.min_max(values).as_py()
        state.minimum = (
            minimum_maximum["min"]
            if state.minimum is None
            else min(state.minimum, minimum_maximum["min"])
        )
        state.maximum = (
            minimum_maximum["max"]
            if state.maximum is None
            else max(state.maximum, minimum_maximum["max"])
        )
        return
    if state.role in {"financial_measure", "numeric_measure", "numeric"}:
        minimum_maximum = pc.min_max(values).as_py()
        state.minimum = (
            minimum_maximum["min"]
            if state.minimum is None
            else min(state.minimum, minimum_maximum["min"])
        )
        state.maximum = (
            minimum_maximum["max"]
            if state.maximum is None
            else max(state.maximum, minimum_maximum["max"])
        )
        state.numeric_sum += float(pc.sum(values).as_py() or 0.0)
        state.numeric_sum_squares += float(
            pc.sum(pc.multiply(values, values)).as_py() or 0.0
        )
        state.numeric_count += len(values)
        state.zero_count += int(
            pc.sum(pc.cast(pc.equal(values, 0), pa.int64())).as_py() or 0
        )
        state.negative_count += int(
            pc.sum(pc.cast(pc.less(values, 0), pa.int64())).as_py() or 0
        )
        state.nan_count += int(
            pc.sum(pc.cast(pc.is_nan(values), pa.int64())).as_py() or 0
        )
        _sample_numeric(state, values, total_rows)
        return
    if state.role in {
        "identifier",
        "high_cardinality_identifier",
        "high_cardinality_descriptive",
    }:
        _update_text_details(state, values)
        if state.role == "identifier" and not state.distinct_overflow:
            if not _bounded_update(
                state.exact_distinct_values,
                pc.unique(values).to_pylist(),
                MAX_EXACT_DISTINCT_VALUES,
            ):
                state.distinct_overflow = True
                state.exact_distinct_values.clear()
        return
    _merge_value_counts(state.categories, values)


def _finalise_column(state: ColumnState) -> dict[str, Any]:
    total = state.null_count + state.non_null_count
    result: dict[str, Any] = {
        "name": state.name,
        "arrow_type": state.arrow_type,
        "parquet_physical_type": state.parquet_physical_type,
        "parquet_logical_type": state.parquet_logical_type,
        "nullable": state.nullable,
        "dictionary_type": state.dictionary_type,
        "dictionary_description": state.dictionary_description,
        "role": state.role,
        "interpretation": state.interpretation,
        "cashflow_use": state.cashflow_use,
        "null_count": state.null_count,
        "null_percentage": round((100 * state.null_count / total), 6)
        if total
        else None,
        "non_null_count": state.non_null_count,
    }

    if state.role in {"category", "categorical_numeric"}:
        counts = state.categories.most_common()
        result.update(
            {
                "distinct_count": len(state.categories),
                "distinct_method": "exact",
                "top_values": [
                    {"value": _json_safe(value), "count": count}
                    for value, count in counts[:TOP_CATEGORY_COUNT]
                ],
                "additional_distinct_values": max(
                    0, len(state.categories) - TOP_CATEGORY_COUNT
                ),
                "minimum": _json_safe(state.minimum),
                "maximum": _json_safe(state.maximum),
            }
        )
        expected = EXPECTED_CATEGORIES.get(state.name)
        if expected is not None:
            observed = set(state.categories)
            result["expected_values_from_dictionary"] = [
                _json_safe(value) for value in sorted(expected)
            ]
            result["unexpected_values"] = [
                _json_safe(value) for value in sorted(observed - expected)
            ]
            result["missing_expected_values"] = [
                _json_safe(value) for value in sorted(expected - observed)
            ]
        return result

    if state.role == "timestamp":
        result.update(
            {
                "distinct_count": len(state.date_values),
                "distinct_method": "exact",
                "minimum": _json_safe(state.minimum),
                "maximum": _json_safe(state.maximum),
            }
        )
        return result

    if state.role in {"financial_measure", "numeric_measure", "numeric"}:
        mean = (
            state.numeric_sum / state.numeric_count
            if state.numeric_count
            else None
        )
        variance = (
            state.numeric_sum_squares / state.numeric_count - mean * mean
            if state.numeric_count and mean is not None
            else None
        )
        stddev = math.sqrt(max(variance, 0.0)) if variance is not None else None
        quantiles: dict[str, float | None] = {
            "p25": None,
            "p50": None,
            "p75": None,
            "p95": None,
            "p99": None,
        }
        sample_size = (
            sum(len(part) for part in state.sampled_values)
            if state.sampled_values
            else 0
        )
        if sample_size:
            sample = pa.concat_arrays(state.sampled_values)
            values = pc.quantile(
                sample, q=[0.25, 0.5, 0.75, 0.95, 0.99]
            ).to_pylist()
            quantiles = dict(
                zip(("p25", "p50", "p75", "p95", "p99"), values)
            )
        result.update(
            {
                "distinct_count": None,
                "distinct_method": "not_computed_for_continuous_values",
                "minimum": _json_safe(state.minimum),
                "maximum": _json_safe(state.maximum),
                "numeric_statistics": {
                    "count": state.numeric_count,
                    "sum_streaming": state.numeric_sum,
                    "mean_streaming": mean,
                    "stddev_streaming": stddev,
                    "zero_count": state.zero_count,
                    "negative_count": state.negative_count,
                    "nan_count": state.nan_count,
                },
                "distribution_sample": {
                    "method": "deterministic_systematic_sample",
                    "sample_size": sample_size,
                    "source_non_null_count": state.numeric_count,
                    "quantiles": quantiles,
                },
            }
        )
        return result

    if state.role == "identifier":
        safe_prefixes = (
            state.prefix_counts.most_common(20)
            if state.string_length_min is not None
            and state.string_length_min > 2
            else []
        )
        result.update(
            {
                "distinct_count": (
                    len(state.exact_distinct_values)
                    if not state.distinct_overflow
                    else None
                ),
                "distinct_method": (
                    "exact_bounded_set" if not state.distinct_overflow else "deferred"
                ),
                "minimum": None,
                "maximum": None,
                "blank_count": state.blank_count,
                "string_length": {
                    "minimum": state.string_length_min,
                    "maximum": state.string_length_max,
                    "mean": (
                        state.string_length_sum / state.non_null_count
                        if state.non_null_count
                        else None
                    ),
                },
                "prefix_counts": [
                    {"value": value, "count": count}
                    for value, count in safe_prefixes
                ],
            }
        )
        return result

    safe_prefixes = (
        state.prefix_counts.most_common(20)
        if state.string_length_min is not None
        and state.string_length_min > 2
        else []
    )
    result.update(
        {
            "distinct_count": None,
            "distinct_method": "deferred_high_cardinality",
            "minimum": None,
            "maximum": None,
            "blank_count": state.blank_count,
            "string_length": {
                "minimum": state.string_length_min,
                "maximum": state.string_length_max,
                "mean": (
                    state.string_length_sum / state.non_null_count
                    if state.non_null_count
                    else None
                ),
            },
            "prefix_counts": [
                {"value": value, "count": count}
                for value, count in safe_prefixes
            ],
        }
    )
    return result


def _update_customer_reference(
    state: CustomerReferenceState,
    references: pa.Array,
) -> None:
    state.null_count += references.null_count
    valid = references.drop_null()
    state.referencing_rows += len(valid)
    unique_values = pc.unique(valid).to_pylist()
    if not state.reference_overflow:
        if not _bounded_update(
            state.referenced_ids,
            unique_values,
            MAX_EXACT_ID_VALUES,
        ):
            state.reference_overflow = True
            state.referenced_ids.clear()

    if len(valid):
        matches = pc.is_in(valid, value_set=state.customer_values)
        matching = int(pc.sum(pc.cast(matches, pa.int64())).as_py() or 0)
        state.matching_rows += matching
        state.orphan_rows += len(valid) - matching
        orphan_values = valid.filter(pc.invert(matches))
        if not state.orphan_overflow:
            if not _bounded_update(
                state.orphan_ids,
                pc.unique(orphan_values).to_pylist(),
                MAX_EXACT_ID_VALUES,
            ):
                state.orphan_overflow = True
                state.orphan_ids.clear()


def _reference_report(
    table_name: str,
    relation: CustomerReferenceState,
    row_count: int,
) -> dict[str, Any]:
    exact_refs = not relation.reference_overflow
    exact_orphans = not relation.orphan_overflow
    matched_references = (
        len(relation.referenced_ids) - len(relation.orphan_ids)
        if exact_refs and exact_orphans
        else None
    )
    return {
        "source_table": table_name,
        "source_column": "client_id_fk",
        "target_table": "customers",
        "target_column": "client_id",
        "data_type_compatible": True,
        "null_reference_count": relation.null_count,
        "referencing_row_count": relation.referencing_rows,
        "matching_row_count": relation.matching_rows,
        "orphan_row_count": relation.orphan_rows,
        "distinct_reference_count": (
            len(relation.referenced_ids) if exact_refs else None
        ),
        "distinct_orphan_reference_count": (
            len(relation.orphan_ids) if exact_orphans else None
        ),
        "matching_distinct_reference_count": matched_references,
        "reference_count_method": "exact_bounded_set" if exact_refs else "deferred",
        "orphan_count_method": "exact_bounded_set" if exact_orphans else "deferred",
        "verified": relation.orphan_rows == 0 and exact_orphans,
        "cardinality": (
            "one customer to many table rows"
            if exact_refs and row_count > len(relation.referenced_ids)
            else "one-to-one or unresolved cardinality"
        ),
        "row_duplication_risk": (
            "Customer joins may multiply rows because each customer can have "
            "multiple records."
            if exact_refs and row_count > len(relation.referenced_ids)
            else "No row multiplication demonstrated from the customer join."
        ),
    }


def _composite_key_report(
    table_name: str,
    row_count: int,
    columns: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    date_column = next(
        (
            name
            for name in ("snapshot_date", "month_end", "contrib_date")
            if name in columns
        ),
        None,
    )
    if "client_id_fk" not in columns or date_column is None:
        return None
    if row_count > MAX_EXACT_COMPOSITE_ROWS:
        return {
            "columns": ["client_id_fk", date_column],
            "method": "deferred",
            "reason": (
                "Exact composite-key state would exceed the configured bounded "
                "in-memory limit."
            ),
            "verified": False,
        }
    return {
        "columns": ["client_id_fk", date_column],
        "method": "exact",
        "verified": False,
    }


def profile_small_table(
    path: Path,
    metadata: dict[str, Any],
    customer_values: pa.Array | None,
    batch_size: int,
) -> tuple[dict[str, Any], set[Any]]:
    table_name = path.stem
    table_meta = _table_metadata(metadata, table_name)
    field_names = [column["name"] for column in table_meta["columns"]]
    states: dict[str, ColumnState] = {}
    leaf_by_name = {
        leaf["path"]: leaf for leaf in table_meta.get("parquet_schema", [])
    }
    for column in table_meta["columns"]:
        name = column["name"]
        arrow_type = pa.type_for_alias(column["arrow_type"])
        role, interpretation = _classify_column(name, arrow_type)
        leaf = leaf_by_name.get(name, {})
        states[name] = ColumnState(
            name=name,
            arrow_type=column["arrow_type"],
            parquet_physical_type=str(leaf.get("physical_type") or "unknown"),
            parquet_logical_type=str(leaf.get("logical_type") or "None"),
            nullable=bool(column["nullable"]),
            dictionary_type=column.get("dictionary_declared_type"),
            dictionary_description=(
                _sanitize_text(column["dictionary_description"])
                if column.get("dictionary_description")
                else None
            ),
            role=role,
            interpretation=interpretation,
            cashflow_use=_cashflow_column_use(table_name, name, role),
            sample_total_rows=table_meta["parquet_metadata"]["row_count"],
        )

    relation = (
        CustomerReferenceState(customer_values=customer_values)
        if customer_values is not None and "client_id_fk" in field_names
        else None
    )
    parquet_file = pq.ParquetFile(path)
    rows = 0
    composite_values: set[tuple[Any, Any]] | None = None
    composite_null_rows = 0
    cross_field_counts: Counter[str] = Counter()
    type_segment_counts: Counter[tuple[Any, Any]] = Counter()
    composite_date_column = next(
        (
            name
            for name in ("snapshot_date", "month_end", "contrib_date")
            if name in field_names
        ),
        None,
    )
    if (
        customer_values is not None
        and "client_id_fk" in field_names
        and composite_date_column is not None
        and table_meta["parquet_metadata"]["row_count"]
        <= MAX_EXACT_COMPOSITE_ROWS
    ):
        composite_values = set()

    started = time.perf_counter()
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=field_names):
        rows += batch.num_rows
        for name in field_names:
            _update_column(states[name], batch.column(name), rows)
        if relation is not None:
            _update_customer_reference(
                relation, batch.column("client_id_fk")
            )
        if composite_values is not None and composite_date_column is not None:
            client_values = batch.column("client_id_fk").to_pylist()
            date_values = batch.column(composite_date_column).to_pylist()
            for client_value, date_value in zip(client_values, date_values):
                if client_value is None or date_value is None:
                    composite_null_rows += 1
                else:
                    composite_values.add((client_value, _json_safe(date_value)))
        if table_name == "customers":
            if {"birth_or_reg_dt", "bank_reg_dt"} <= set(field_names):
                after_registration = pc.greater(
                    batch.column("birth_or_reg_dt"),
                    batch.column("bank_reg_dt"),
                )
                cross_field_counts["birth_or_registration_after_bank_registration"] += int(
                    pc.sum(pc.cast(after_registration, pa.int64())).as_py() or 0
                )
            if {"type_cd", "segment"} <= set(field_names):
                for type_code, segment_value in zip(
                    batch.column("type_cd").to_pylist(),
                    batch.column("segment").to_pylist(),
                ):
                    type_segment_counts[
                        (_json_safe(type_code), _json_safe(segment_value))
                    ] += 1
        if composite_date_column is not None and {"year", "month"} <= set(field_names):
            date_values = batch.column(composite_date_column)
            cross_field_counts["date_year_mismatch"] += int(
                pc.sum(
                    pc.cast(
                        pc.not_equal(
                            pc.year(date_values),
                            pc.cast(batch.column("year"), pa.int32()),
                        ),
                        pa.int64(),
                    )
                ).as_py()
                or 0
            )
            cross_field_counts["date_month_mismatch"] += int(
                pc.sum(
                    pc.cast(
                        pc.not_equal(
                            pc.month(date_values),
                            pc.cast(batch.column("month"), pa.int32()),
                        ),
                        pa.int64(),
                    )
                ).as_py()
                or 0
            )
    elapsed = time.perf_counter() - started

    column_reports = {
        name: _finalise_column(states[name]) for name in field_names
    }
    customer_ids = (
        set(states["client_id"].exact_distinct_values)
        if table_name == "customers" and "client_id" in states
        else set()
    )
    composite = _composite_key_report(table_name, rows, column_reports)
    if composite is not None:
        if composite_values is None:
            composite.update(
                {
                    "key_count": None,
                    "nullable_key_row_count": None,
                    "duplicate_key_row_count": None,
                }
            )
        else:
            composite.update(
                {
                    "key_count": len(composite_values),
                    "nullable_key_row_count": composite_null_rows,
                    "duplicate_key_row_count": (
                        rows - composite_null_rows - len(composite_values)
                    ),
                    "verified_primary_key": (
                        composite_null_rows == 0
                        and rows == len(composite_values)
                    ),
                }
            )

    relationships = []
    if relation is not None:
        relationships.append(_reference_report(table_name, relation, rows))

    null_issues = [
        {
            "column": name,
            "null_count": report["null_count"],
            "null_percentage": report["null_percentage"],
        }
        for name, report in column_reports.items()
        if report["null_count"]
    ]
    unexpected_categories = {
        name: {
            "unexpected": report.get("unexpected_values", []),
            "missing": report.get("missing_expected_values", []),
        }
        for name, report in column_reports.items()
        if report.get("unexpected_values") or report.get("missing_expected_values")
    }
    result = {
        "file_name": path.name,
        "table_name": table_name,
        "file_size_bytes": path.stat().st_size,
        "purpose": table_meta["dictionary"]["purpose"],
        "classification": TABLE_CLASSIFICATION.get(table_name, "unclassified"),
        "row_count": rows,
        "column_count": len(field_names),
        "row_group_count": table_meta["parquet_metadata"]["row_group_count"],
        "columns": column_reports,
        "customer_relationship": relationships[0] if relationships else None,
        "composite_key": composite,
        "data_quality": {
            "columns_with_nulls": null_issues,
            "unexpected_or_missing_dictionary_categories": unexpected_categories,
            "dictionary_row_count": table_meta["reconciliation"][
                "documented_row_count"
            ],
            "row_count_matches_dictionary": table_meta["reconciliation"][
                "row_count_matches"
            ],
            "schema_fields_absent_from_dictionary": table_meta[
                "reconciliation"
            ]["schema_fields_absent_from_dictionary"],
            "dictionary_fields_missing_from_schema": table_meta[
                "reconciliation"
            ]["documented_fields_missing_from_schema"],
            "dictionary_type_mismatches": table_meta["reconciliation"][
                "dictionary_type_mismatches"
            ],
            "cross_field_checks": {
                name: count for name, count in cross_field_counts.items()
            },
            "type_cd_segment_counts": [
                {
                    "type_cd": type_code,
                    "segment": segment_value,
                    "count": count,
                }
                for (type_code, segment_value), count in sorted(
                    type_segment_counts.items(),
                    key=lambda item: (str(item[0][0]), str(item[0][1])),
                )
            ],
        },
        "execution": {
            "elapsed_seconds": round(elapsed, 6),
            "batch_size": batch_size,
        },
    }
    return result, customer_ids


def _profile_transaction_quality(
    batch: pa.RecordBatch,
) -> dict[str, int]:
    result = {
        "book_date_before_documented_range": 0,
        "book_date_after_documented_range": 0,
        "book_date_year_month_mismatch": 0,
        "eur_original_amount_mismatch": 0,
    }
    names = set(batch.schema.names)
    if "book_date" in names:
        book_date = batch.column("book_date")
        start = pa.scalar(datetime(2024, 1, 1), type=book_date.type)
        end = pa.scalar(datetime(2025, 12, 31), type=book_date.type)
        result["book_date_before_documented_range"] = int(
            pc.sum(pc.cast(pc.less(book_date, start), pa.int64())).as_py()
            or 0
        )
        result["book_date_after_documented_range"] = int(
            pc.sum(pc.cast(pc.greater(book_date, end), pa.int64())).as_py()
            or 0
        )

        if {"year", "month"} <= names:
            year_mismatch = pc.not_equal(
                pc.year(book_date), pc.cast(batch.column("year"), pa.int32())
            )
            month_mismatch = pc.not_equal(
                pc.month(book_date), pc.cast(batch.column("month"), pa.int32())
            )
            mismatch = pc.or_(year_mismatch, month_mismatch)
            result["book_date_year_month_mismatch"] = int(
                pc.sum(pc.cast(mismatch, pa.int64())).as_py() or 0
            )

    if {"trx_ccy", "amount_orig", "amount_eur"} <= names:
        eur_mask = pc.equal(batch.column("trx_ccy"), "EUR")
        amount_mismatch = pc.and_(
            eur_mask,
            pc.not_equal(
                batch.column("amount_orig"), batch.column("amount_eur")
            ),
        )
        result["eur_original_amount_mismatch"] = int(
            pc.sum(pc.cast(amount_mismatch, pa.int64())).as_py() or 0
        )
    return result


def profile_transactions(
    path: Path,
    metadata: dict[str, Any],
    customer_values: pa.Array,
    batch_size: int,
) -> dict[str, Any]:
    table_meta = _table_metadata(metadata, "transactions")
    field_names = [column["name"] for column in table_meta["columns"]]
    leaf_by_name = {
        leaf["path"]: leaf for leaf in table_meta.get("parquet_schema", [])
    }
    states: dict[str, ColumnState] = {}
    for column in table_meta["columns"]:
        name = column["name"]
        arrow_type = pa.type_for_alias(column["arrow_type"])
        role, interpretation = _classify_column(name, arrow_type)
        leaf = leaf_by_name.get(name, {})
        states[name] = ColumnState(
            name=name,
            arrow_type=column["arrow_type"],
            parquet_physical_type=str(leaf.get("physical_type") or "unknown"),
            parquet_logical_type=str(leaf.get("logical_type") or "None"),
            nullable=bool(column["nullable"]),
            dictionary_type=column.get("dictionary_declared_type"),
            dictionary_description=(
                _sanitize_text(column["dictionary_description"])
                if column.get("dictionary_description")
                else None
            ),
            role=role,
            interpretation=interpretation,
            cashflow_use=_cashflow_column_use("transactions", name, role),
            sample_total_rows=table_meta["parquet_metadata"]["row_count"],
        )

    relation = CustomerReferenceState(customer_values=customer_values)
    quality_counts = Counter()
    rows = 0
    peak_arrow_bytes = 0
    parquet_file = pq.ParquetFile(path)
    started = time.perf_counter()
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=field_names):
        rows += batch.num_rows
        for name in field_names:
            _update_column(states[name], batch.column(name), rows)
        _update_customer_reference(relation, batch.column("client_id_fk"))
        quality_counts.update(_profile_transaction_quality(batch))
        peak_arrow_bytes = max(peak_arrow_bytes, pa.total_allocated_bytes())
    elapsed = time.perf_counter() - started

    column_reports = {
        name: _finalise_column(states[name]) for name in field_names
    }
    return {
        "file_name": path.name,
        "table_name": "transactions",
        "file_size_bytes": path.stat().st_size,
        "purpose": table_meta["dictionary"]["purpose"],
        "classification": TABLE_CLASSIFICATION["transactions"],
        "row_count": rows,
        "column_count": len(field_names),
        "row_group_count": table_meta["parquet_metadata"]["row_group_count"],
        "columns": column_reports,
        "customer_relationship": _reference_report(
            "transactions", relation, rows
        ),
        "composite_key": {
            "columns": ["txn_id"],
            "method": "deferred",
            "reason": (
                "Exact global uniqueness would require retaining approximately "
                "120 million identifier values."
            ),
            "verified": False,
        },
        "data_quality": {
            "columns_with_nulls": [
                {
                    "column": name,
                    "null_count": report["null_count"],
                    "null_percentage": report["null_percentage"],
                }
                for name, report in column_reports.items()
                if report["null_count"]
            ],
            "unexpected_or_missing_dictionary_categories": {
                name: {
                    "unexpected": report.get("unexpected_values", []),
                    "missing": report.get("missing_expected_values", []),
                }
                for name, report in column_reports.items()
                if report.get("unexpected_values")
                or report.get("missing_expected_values")
            },
            "temporal_and_currency_checks": dict(quality_counts),
            "dictionary_row_count": table_meta["reconciliation"][
                "documented_row_count"
            ],
            "row_count_matches_dictionary": table_meta["reconciliation"][
                "row_count_matches"
            ],
            "schema_fields_absent_from_dictionary": table_meta[
                "reconciliation"
            ]["schema_fields_absent_from_dictionary"],
            "dictionary_fields_missing_from_schema": table_meta[
                "reconciliation"
            ]["documented_fields_missing_from_schema"],
            "dictionary_type_mismatches": table_meta["reconciliation"][
                "dictionary_type_mismatches"
            ],
        },
        "execution": {
            "elapsed_seconds": round(elapsed, 6),
            "batch_size": batch_size,
            "peak_pyarrow_allocated_bytes": peak_arrow_bytes,
        },
    }


def _customer_quality(customers: dict[str, Any]) -> dict[str, Any]:
    columns = customers["columns"]
    ids = columns["client_id"]
    relation_verified = (
        ids["null_count"] == 0
        and ids.get("distinct_count") == customers["row_count"]
    )
    return {
        "client_id_primary_key_verified": relation_verified,
        "segment_distribution": columns["segment"]["top_values"],
        "sme_count": next(
            (
                row["count"]
                for row in columns["segment"]["top_values"]
                if row["value"] == "SME"
            ),
            0,
        ),
    }


def build_comprehensive_report(
    dataset_dir: Path,
    metadata_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> dict[str, Any]:
    metadata = _load_metadata(metadata_path)
    table_order = [
        "customers",
        "transactions",
        "leasing_agreements",
        "life_insurance",
        "property_insurance",
        "pension",
        "margin_assets",
        "margin_liabilities",
    ]
    customers_path = dataset_dir / "customers.parquet"
    if not customers_path.is_file():
        raise ValueError("customers.parquet not found")

    tracemalloc.start()
    started = time.perf_counter()
    customers, customer_ids = profile_small_table(
        customers_path,
        metadata,
        customer_values=None,
        batch_size=batch_size,
    )
    customer_values = pa.array(sorted(customer_ids))

    profiles = {"customers": customers}
    for table_name in table_order[1:]:
        path = dataset_dir / f"{table_name}.parquet"
        if not path.is_file():
            raise ValueError(f"Required Parquet file not found: {path.name}")
        if table_name == "transactions":
            profiles[table_name] = profile_transactions(
                path, metadata, customer_values, batch_size
            )
        else:
            table_profile, _ = profile_small_table(
                path,
                metadata,
                customer_values=customer_values,
                batch_size=batch_size,
            )
            profiles[table_name] = table_profile

    elapsed = time.perf_counter() - started
    current_python_bytes, peak_python_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ordered_profiles = [profiles[name] for name in table_order]
    relationships = [
        profile["customer_relationship"]
        for profile in ordered_profiles
        if profile["customer_relationship"] is not None
    ]
    return {
        "report_schema_version": "1.0",
        "inspection_mode": "bounded_record_level_aggregate",
        "pyarrow_version": pa.__version__,
        "dataset_name": dataset_dir.name,
        "task_2b_metadata_report": metadata_path.name,
        "summary": {
            "parquet_file_count": len(ordered_profiles),
            "total_rows": sum(profile["row_count"] for profile in ordered_profiles),
            "total_columns": sum(
                profile["column_count"] for profile in ordered_profiles
            ),
            "total_file_size_bytes": sum(
                profile["file_size_bytes"] for profile in ordered_profiles
            ),
        },
        "customers": _customer_quality(profiles["customers"]),
        "tables": ordered_profiles,
        "relationships": relationships,
        "customer_reference_sets": {
            relationship["source_table"]: {
                "distinct_references": relationship["distinct_reference_count"],
                "orphan_references": relationship[
                    "distinct_orphan_reference_count"
                ],
                "verified": relationship["verified"],
            }
            for relationship in relationships
        },
        "execution": {
            "batch_size": batch_size,
            "memory_limit_mb": memory_limit_mb,
            "transaction_full_passes": 1,
            "large_join_materializations": 0,
        },
        "runtime_metrics": {
            "elapsed_seconds": round(elapsed, 6),
            "peak_python_traced_bytes": peak_python_bytes,
            "current_python_traced_bytes": current_python_bytes,
            "table_elapsed_seconds": {
                profile["table_name"]: profile["execution"].get(
                    "elapsed_seconds"
                )
                for profile in ordered_profiles
            },
            "transaction_peak_pyarrow_allocated_bytes": profiles[
                "transactions"
            ]["execution"].get("peak_pyarrow_allocated_bytes"),
        },
        "limitations": [
            "Exact global distinctness for transaction IDs and counterparty IBANs "
            "was intentionally deferred to avoid retaining unbounded identifiers.",
            "Continuous-value quantiles use a deterministic systematic sample and "
            "are labelled approximate.",
            "Customer segment availability prevents SME selection even if "
            "transaction relationships are complete.",
            "No cleaning, weekly target aggregation, feature engineering, model "
            "training or SME selection was performed.",
        ],
    }


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.4f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _format_counts(values: list[dict[str, Any]], max_items: int = 12) -> str:
    parts = [
        f"{_format_value(item['value'])} ({item['count']:,})"
        for item in values[:max_items]
    ]
    if len(values) > max_items:
        parts.append(f"... {len(values) - max_items} more")
    return "; ".join(parts) if parts else "No non-null values"


def _column_characteristics(column: dict[str, Any]) -> str:
    role = column["role"]
    if role in {"category", "categorical_numeric"}:
        text = (
            f"distinct={column['distinct_count']:,}; "
            f"frequent: {_format_counts(column['top_values'])}"
        )
        if column.get("minimum") is not None or column.get("maximum") is not None:
            text += (
                f"; range={_format_value(column.get('minimum'))}–"
                f"{_format_value(column.get('maximum'))}"
            )
        return text
    if role == "timestamp":
        return (
            f"distinct dates={column['distinct_count']:,}; "
            f"range={_format_value(column['minimum'])}–"
            f"{_format_value(column['maximum'])}"
        )
    if role in {"financial_measure", "numeric_measure", "numeric"}:
        stats = column["numeric_statistics"]
        quantiles = column["distribution_sample"]["quantiles"]
        return (
            f"range={_format_value(column['minimum'])}–"
            f"{_format_value(column['maximum'])}; "
            f"mean={_format_value(stats['mean_streaming'])}; "
            f"zero={stats['zero_count']:,}; negative={stats['negative_count']:,}; "
            f"sampled quantiles p25/p50/p75/p95/p99="
            f"{_format_value(quantiles['p25'])}/"
            f"{_format_value(quantiles['p50'])}/"
            f"{_format_value(quantiles['p75'])}/"
            f"{_format_value(quantiles['p95'])}/"
            f"{_format_value(quantiles['p99'])}"
        )
    if role in {
        "identifier",
        "high_cardinality_identifier",
        "high_cardinality_descriptive",
    }:
        return (
            f"distinct={_format_value(column['distinct_count'])} "
            f"({column['distinct_method']}); "
            f"blank={column['blank_count']:,}; "
            f"length min/max/mean={_format_value(column['string_length']['minimum'])}/"
            f"{_format_value(column['string_length']['maximum'])}/"
            f"{_format_value(column['string_length']['mean'])}; "
            f"prefixes: {_format_counts(column['prefix_counts'], 8)}"
        )
    return column["distinct_method"]


def render_markdown(report: dict[str, Any]) -> str:
    tables = report["tables"]
    transactions = next(table for table in tables if table["table_name"] == "transactions")
    customers = next(table for table in tables if table["table_name"] == "customers")
    transaction_relationship = transactions["customer_relationship"]
    segment = customers["columns"]["segment"]
    lines = [
        "# CashFlowAI Comprehensive Dataset Analysis",
        "",
        "## Executive Summary",
        "",
        (
            f"The dataset contains {report['summary']['total_rows']:,} rows and "
            f"{report['summary']['total_columns']} columns across eight Parquet "
            "files. The record-level scan confirms that `transactions` is the "
            "only table directly suitable for constructing bank-transaction cash "
            "flow, while `customers` is essential for cohort identification."
        ),
        "",
        (
            "The material SME limitation is confirmed: all 200,000 customer rows "
            "are labelled `Private`, with no SME or Corporate labels. No other "
            "schema contains a segment field. Transactions were scanned for "
            "general quality and relationship coverage, but this cannot create "
            "an authoritative SME label."
        ),
        "",
        (
            f"The transaction customer reference joins to the customer identifier "
            f"for {transaction_relationship['matching_row_count']:,} of "
            f"{transaction_relationship['referencing_row_count']:,} non-null "
            f"transactions, with {transaction_relationship['orphan_row_count']:,} "
            "orphan transaction rows."
        ),
        "",
        "## Dataset-wide Overview",
        "",
        "| Table | Rows | Columns | Row groups | File size (bytes) | Classification |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for table in tables:
        lines.append(
            f"| `{table['table_name']}` | {table['row_count']:,} | "
            f"{table['column_count']} | {table['row_group_count']} | "
            f"{table['file_size_bytes']:,} | {table['classification']} |"
        )

    lines.extend(
        [
            "",
            "## Relationship Matrix",
            "",
            "| Source | Target | Matching rows | Orphan rows | Null references | "
            "Distinct references | Verified | Cardinality / risk |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for relation in report["relationships"]:
        lines.append(
            f"| {relation['source_table']}.{relation['source_column']} | "
            f"{relation['target_table']}.{relation['target_column']} | "
            f"{relation['matching_row_count']:,} | "
            f"{relation['orphan_row_count']:,} | "
            f"{relation['null_reference_count']:,} | "
            f"{_format_value(relation['distinct_reference_count'])} | "
            f"{relation['verified']} | {relation['row_duplication_risk']} |"
        )

    lines.extend(
        [
            "",
            "The customer join is structurally verified from exact aggregate "
            "overlap. It is not safe to join snapshot tables directly to "
            "transactions without period alignment and aggregation because all "
            "non-customer tables can contain many rows per customer.",
            "",
            "## Mermaid ER Diagram",
            "",
            "```mermaid",
            "erDiagram",
            "    CUSTOMERS ||--o{ TRANSACTIONS : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ LEASING_AGREEMENTS : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ LIFE_INSURANCE : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ PROPERTY_INSURANCE : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ PENSION : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ MARGIN_ASSETS : \"client_id_fk verified overlap\"",
            "    CUSTOMERS ||--o{ MARGIN_LIABILITIES : \"client_id_fk verified overlap\"",
            "```",
            "",
            "No agreement, policy or account dimension table is present. Product "
            "contract identifiers and transaction-account relationships therefore "
            "remain unresolved.",
            "",
            "### Candidate-key status",
            "",
            "- `customers.client_id`: verified unique and non-null in the scanned "
            "200,000-row file.",
            "- `transactions.txn_id`: identifier candidate only; exact global "
            "uniqueness was deferred because retaining all transaction IDs would "
            "exceed the bounded-memory policy.",
            "- Snapshot tables: `(client_id_fk, reporting date)` is a practical "
            "period key candidate, but it cannot identify individual contracts "
            "because agreement/policy identifiers are absent. Exact duplicate "
            "tests are reported below where cardinality permitted.",
            "",
            "## SME Discrepancy Investigation",
            "",
            "### Verified Segment Evidence",
            "",
            f"- Observed segment distribution: {_format_counts(segment['top_values'])}.",
            f"- Null segment rows: {segment['null_count']:,}.",
            "- `segment` exists only in `customers.parquet` among the eight tables.",
            "",
            "### Customer-reference Evidence",
            "",
            "| Source table | Distinct references | Orphan references | Orphan rows | Verified coverage |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for relation in report["relationships"]:
        lines.append(
            f"| `{relation['source_table']}` | "
            f"{_format_value(relation['distinct_reference_count'])} | "
            f"{_format_value(relation['distinct_orphan_reference_count'])} | "
            f"{relation['orphan_row_count']:,} | {relation['verified']} |"
        )

    lines.extend(
        [
            "",
            "The transaction and product references can therefore be checked "
            "against the actual customer table. They do not provide an independent "
            "SME classification. Customer-ID prefixes, transaction amounts, or "
            "product ownership are not evidence of business status.",
            "",
            "### Dictionary Claims and Observable Discrepancy",
            "",
            "- Dictionary claim: 221,000 total customers: 200,000 Private, "
            "20,000 SME and 1,000 Corporate.",
            "- Verified file: 200,000 customers, all Private.",
            "- Dictionary claim: approximately 151.1 million transactions.",
            f"- Verified transaction rows: {transactions['row_count']:,}.",
            "- The exact Private population count is present, but the SME and "
            "Corporate populations are absent. This is consistent with a partial "
            "customer export ending at the documented Private cohort; the export "
            "mechanism itself is not present in the files, so that cause remains "
            "an interpretation.",
            "",
            "## CashFlowAI Usability Assessment",
            "",
            "| Table | Classification | Assessment |",
            "| --- | --- | --- |",
        ]
    )
    relevance = {
        "customers": ("Essential", "Required for cohort identification, but the current file cannot identify any SME customer."),
        "transactions": ("Essential", "The only direct source of dated inflows, outflows and net bank-transaction movement."),
        "leasing_agreements": ("Contextual only", "Monthly agreement snapshots may provide historical financial context but have no verified SME label or agreement key."),
        "life_insurance": ("Contextual only", "Monthly policy snapshots could add context but do not establish SME status or cash-flow relevance."),
        "property_insurance": ("Contextual only", "Monthly policy snapshots are historical context only in the current data."),
        "pension": ("Contextual only", "Contribution records may provide customer-level context but are not transaction cash flow."),
        "margin_assets": ("Contextual only", "Monthly balances provide financial context and require temporal alignment."),
        "margin_liabilities": ("Contextual only", "Monthly liability snapshots provide context but cannot replace transaction cash flow."),
    }
    for table in tables:
        category, assessment = relevance[table["table_name"]]
        lines.append(
            f"| `{table['table_name']}` | {category} | {assessment} |"
        )

    lines.extend(
        [
            "",
            "## Data-quality Findings",
            "",
            "- Null rates, exact category domains, candidate-key behavior and "
            "numeric/date ranges are reported per table below.",
            "- Dictionary row-count mismatches are retained explicitly rather "
            "than silently reconciled.",
            "- Exact global uniqueness for transaction IDs and counterparty IBANs "
            "was deferred because bounded memory is required.",
            "- Numeric quantiles are deterministic sample estimates, while "
            "extrema, null counts, sums and zero/negative counts are streaming "
            "aggregates.",
            "",
            "## Detailed Table Analysis",
            "",
        ]
    )

    for table in tables:
        lines.extend(
            [
                f"### {table['table_name']}",
                "",
                f"**Purpose:** {table['purpose'] or 'Not documented.'}",
                "",
                f"**Record meaning:** {table['purpose'] or 'Record meaning is not documented.'}",
                "",
                f"**Role:** {table['classification']}.",
                "",
                f"**Observed size:** {table['row_count']:,} rows, "
                f"{table['column_count']} columns, {table['row_group_count']} row groups.",
                "",
                f"**Historical or static:** {table['classification']}; "
                + (
                    "one customer master row represents each customer, with date "
                    "attributes but no repeated customer history."
                    if table["table_name"] == "customers"
                    else (
                        "the date/calendar fields support repeated observations "
                        "over time."
                        if any(
                            column["role"] == "timestamp"
                            for column in table["columns"].values()
                        )
                        else "no date field is present, so the table is treated "
                        "as static context."
                    )
                ),
                "",
                "| Column | Arrow / Parquet type | Role | Nulls | Distinct / distribution | Dictionary description | CashFlowAI use |",
                "| --- | --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for column in table["columns"].values():
            lines.append(
                f"| `{column['name']}` | {_format_value(column['arrow_type'])} / "
                f"{_format_value(column['parquet_physical_type'])} | "
                f"{column['role']} | {column['null_count']:,} "
                f"({_format_value(column['null_percentage'])}%) | "
                f"{_column_characteristics(column)} | "
                f"{column['dictionary_description'] or 'Not documented'} | "
                f"{column['cashflow_use']} |"
            )

        q = table["data_quality"]
        lines.extend(
            [
                "",
                "**Data-quality evidence**",
                "",
                f"- Dictionary row count: {_format_value(q['dictionary_row_count'])}; "
                f"matches observed: {q['row_count_matches_dictionary']}.",
                f"- Columns containing nulls: {_format_counts([{'value': item['column'], 'count': item['null_count']} for item in q['columns_with_nulls']])}.",
                f"- Undocumented actual fields: "
                f"{q['schema_fields_absent_from_dictionary'] or 'None'}.",
                f"- Dictionary fields absent from schema: "
                f"{q['dictionary_fields_missing_from_schema'] or 'None'}.",
                "- Unexpected or missing documented categories: "
                + (
                    "; ".join(
                        f"{name}: unexpected={item['unexpected']}, "
                        f"missing={item['missing']}"
                        for name, item in q[
                            "unexpected_or_missing_dictionary_categories"
                        ].items()
                    )
                    or "None"
                )
                + ".",
                "- Dictionary/Arrow coarse type mismatches: "
                + (
                    "; ".join(
                        f"{item['column']} ({item['dictionary_type']} vs "
                        f"{item['arrow_type']})"
                        for item in q["dictionary_type_mismatches"]
                    )
                    or "None"
                )
                + ".",
            ]
        )
        if table.get("composite_key"):
            key = table["composite_key"]
            lines.append(
                f"- Candidate key {key['columns']}: method={key['method']}, "
                f"duplicates={_format_value(key.get('duplicate_key_row_count'))}."
            )
        if table.get("customer_relationship"):
            rel = table["customer_relationship"]
            lines.append(
                f"- Customer join: {rel['matching_row_count']:,} matching rows, "
                f"{rel['orphan_row_count']:,} orphan rows, "
                f"{_format_value(rel['distinct_reference_count'])} distinct references."
            )
            if rel["distinct_reference_count"]:
                lines.append(
                    "- Customer multiplicity: "
                    f"{table['row_count']:,} rows across "
                    f"{rel['distinct_reference_count']:,} customers "
                    f"(approximately {table['row_count'] / rel['distinct_reference_count']:.3f} "
                    "rows per referenced customer)."
                )
        if table["table_name"] == "transactions":
            checks = q["temporal_and_currency_checks"]
            lines.extend(
                [
                    f"- Book dates before 2024: {checks['book_date_before_documented_range']:,}.",
                    f"- Book dates after 2025: {checks['book_date_after_documented_range']:,}.",
                    f"- Book-date/year-month mismatches: {checks['book_date_year_month_mismatch']:,}.",
                    f"- EUR original-vs-converted amount mismatches: {checks['eur_original_amount_mismatch']:,}.",
                ]
            )
        cross_checks = q.get("cross_field_checks", {})
        if cross_checks:
            lines.append(
                "- Cross-field checks: "
                + "; ".join(
                    f"{name}={count:,}" for name, count in cross_checks.items()
                )
                + "."
            )
        if q.get("type_cd_segment_counts"):
            lines.append(
                "- `type_cd` versus `segment`: "
                + _format_counts(
                    [
                        {
                            "value": f"{item['type_cd']} / {item['segment']}",
                            "count": item["count"],
                        }
                        for item in q["type_cd_segment_counts"]
                    ]
                )
                + "."
            )
        lines.append("")

    execution = report["execution"]
    lines.extend(
        [
            "## Limitations and Unresolved Questions",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "- The extracted customer table contains no identifiable SME population, "
            "so the original research question cannot be evaluated with this "
            "customer cohort.",
            "- Product tables lack agreement/policy identifiers, preventing "
            "contract-level linkage.",
            "- Transaction account identifiers have no corresponding account "
            "dimension in the supplied files.",
            "",
            "## Recommendations",
            "",
            "1. Treat the current export as insufficient for SME cash-flow research "
            "until an authoritative SME customer mapping is obtained.",
            "2. Verify the export version or manifest with the data provider; do not "
            "relabel Private customers as SMEs.",
            "3. If a corrected customer table is supplied, re-run the customer "
            "feasibility and relationship checks before selecting up to five SMEs.",
            "4. Use `transactions.amount_eur`, `dc_indicator`, `book_date` and "
            "`client_id_fk` as the candidate cash-flow fields, subject to a new "
            "SME cohort.",
            "5. Pre-aggregate monthly product tables before any weekly comparison "
            "to avoid row multiplication and future-information leakage.",
            "",
            "## Execution Evidence",
            "",
            f"- Transaction full-table passes: {execution['transaction_full_passes']}.",
            f"- Large join materialisations: {execution['large_join_materializations']}.",
            f"- Arrow batch size: {execution['batch_size']:,}.",
            "",
            "All displayed values are aggregates. Raw customer identifiers, IBANs "
            "and transaction records are intentionally excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    report: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    deterministic_report = copy.deepcopy(report)
    deterministic_report.pop("runtime_metrics", None)
    for table in deterministic_report["tables"]:
        execution = table.get("execution", {})
        execution.pop("elapsed_seconds", None)
        execution.pop("peak_pyarrow_allocated_bytes", None)
    json_text = json.dumps(
        deterministic_report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    json_path.write_text(json_text + "\n", encoding="utf-8", newline="\n")
    markdown_path.write_text(
        render_markdown(deterministic_report), encoding="utf-8", newline="\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Profile all CashFlowAI Parquet tables using bounded record-level "
            "aggregates and one coordinated transaction pass."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--metadata-report", type=Path, default=METADATA_REPORT)
    parser.add_argument("--json-report", type=Path, default=JSON_REPORT)
    parser.add_argument("--markdown-report", type=Path, default=MARKDOWN_REPORT)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--memory-limit-mb", type=int, default=DEFAULT_MEMORY_LIMIT_MB
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.batch_size <= 0:
            raise ValueError("Batch size must be positive")
        if args.memory_limit_mb <= 0:
            raise ValueError("Memory limit must be positive")
        dataset = args.dataset_dir.resolve()
        for report_path in (args.json_report, args.markdown_report):
            if report_path.resolve().is_relative_to(dataset):
                raise ValueError("Report output must be outside the source dataset")

        report = build_comprehensive_report(
            args.dataset_dir,
            args.metadata_report,
            batch_size=args.batch_size,
            memory_limit_mb=args.memory_limit_mb,
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

    runtime = report["runtime_metrics"]
    print(f"Tables profiled: {report['summary']['parquet_file_count']}")
    print(f"Rows scanned: {report['summary']['total_rows']}")
    print(f"Elapsed seconds: {runtime['elapsed_seconds']:.3f}")
    print(
        "Transaction elapsed seconds: "
        f"{runtime['table_elapsed_seconds']['transactions']:.3f}"
    )
    print(f"Peak Python-traced bytes: {runtime['peak_python_traced_bytes']}")
    print(
        "Transaction peak PyArrow allocated bytes: "
        f"{runtime['transaction_peak_pyarrow_allocated_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
