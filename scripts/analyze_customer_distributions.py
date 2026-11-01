#!/usr/bin/env python3
"""Measure customer transaction and weekly cash-flow distributions."""

from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import sys
import time
from array import array
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

try:
    from scripts.check_sme_feasibility import identify_columns
except ModuleNotFoundError:
    from check_sme_feasibility import identify_columns


DATASET_DIR = Path("synthetic_banking/student_export")
METADATA_REPORT = Path(
    "reports/data_inspection/parquet_inventory_summary.json"
)
JSON_REPORT = Path(
    "reports/data_inspection/customer_distribution_analysis.json"
)
MARKDOWN_REPORT = Path(
    "reports/data_inspection/customer_distribution_analysis.md"
)
DEFAULT_BATCH_SIZE = 131_072
STUDY_START = date(2024, 1, 1)
STUDY_END = date(2025, 12, 31)
COMPLETE_WEEKS = 104
TOTAL_DAYS = 731
PARTIAL_WEEK_START_DAY = COMPLETE_WEEKS * 7
SAMPLE_LIMIT = 100_000
WEEKLY_COUNT_THRESHOLDS = (1, 10, 50, 100, 200, 400)
ACTIVE_WEEK_THRESHOLDS = (1, 12, 26, 52, 78)
HISTORY_DAY_THRESHOLDS = (1, 90, 180, 365, 547)
RECOMMENDED_ELIGIBILITY = {
    "minimum_transactions": 50,
    "minimum_active_weeks": 26,
    "minimum_history_days": 180,
    "active_in_both_years": True,
}


def _load_metadata(path: Path) -> dict[str, Any]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("inspection_mode") != "metadata_only":
        raise ValueError("Expected the Task 2B metadata-only report")
    return metadata


def _quantile(sorted_values: Sequence[float | int], q: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    )


def _distribution(values: Iterable[float | int]) -> dict[str, Any]:
    materialised = sorted(values)
    count = len(materialised)
    if count == 0:
        return {
            "count": 0,
            "minimum": None,
            "p05": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "maximum": None,
            "mean": None,
        }
    return {
        "count": count,
        "minimum": materialised[0],
        "p05": _quantile(materialised, 0.05),
        "p25": _quantile(materialised, 0.25),
        "median": _quantile(materialised, 0.5),
        "p75": _quantile(materialised, 0.75),
        "p90": _quantile(materialised, 0.9),
        "p95": _quantile(materialised, 0.95),
        "p99": _quantile(materialised, 0.99),
        "maximum": materialised[-1],
        "mean": statistics.fmean(materialised),
    }


def _weighted_distribution(counter: Counter[int]) -> dict[str, Any]:
    count = sum(counter.values())
    if not count:
        return _distribution([])

    def weighted_quantile(q: float) -> float:
        threshold = max(1, math.ceil(q * count))
        cumulative = 0
        for value, frequency in sorted(counter.items()):
            cumulative += frequency
            if cumulative >= threshold:
                return float(value)
        return float(max(counter))

    total = sum(value * frequency for value, frequency in counter.items())
    return {
        "count": count,
        "minimum": min(counter),
        "p05": weighted_quantile(0.05),
        "p25": weighted_quantile(0.25),
        "median": weighted_quantile(0.5),
        "p75": weighted_quantile(0.75),
        "p90": weighted_quantile(0.9),
        "p95": weighted_quantile(0.95),
        "p99": weighted_quantile(0.99),
        "maximum": max(counter),
        "mean": total / count,
    }


def _sample_distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        **_distribution(values),
        "method": "deterministic systematic sample",
        "sample_size": len(values),
        "note": "Quantiles are estimates; counts and extrema are reported separately.",
    }


def _day_index_distribution(day_indices: Sequence[int]) -> dict[str, Any]:
    distribution = _distribution(day_indices)
    if not day_indices:
        return {
            **distribution,
            "distinct_dates": 0,
            "p05_date": None,
            "median_date": None,
            "p95_date": None,
        }
    dates = [
        STUDY_START + timedelta(days=round(distribution[key]))
        for key in ("minimum", "p05", "median", "p95", "maximum")
    ]
    return {
        **distribution,
        "minimum_date": dates[0].isoformat(),
        "p05_date": dates[1].isoformat(),
        "median_date": dates[2].isoformat(),
        "p95_date": dates[3].isoformat(),
        "maximum_date": dates[4].isoformat(),
        "distinct_dates": len(set(day_indices)),
    }


def load_customer_universe(path: Path) -> tuple[list[Any], Counter[Any], int]:
    parquet_file = pq.ParquetFile(path)
    columns = [
        column["name"] for column in _customer_column_metadata()
    ]
    identifiers: list[Any] = []
    identifier_segments: list[tuple[Any, Any]] = []
    segments: Counter[Any] = Counter()
    rows = 0
    for batch in parquet_file.iter_batches(batch_size=65_536, columns=columns):
        rows += batch.num_rows
        batch_identifiers = batch.column("client_id").to_pylist()
        batch_segments = batch.column("segment").to_pylist()
        identifiers.extend(batch_identifiers)
        identifier_segments.extend(zip(batch_identifiers, batch_segments))
        segments.update(batch_segments)
    if any(identifier is None for identifier in identifiers):
        raise ValueError("Customer identifiers contain nulls")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Customer identifiers are not unique")
    private_identifiers = [
        identifier
        for identifier, segment in identifier_segments
        if segment == "Private"
    ]
    return sorted(private_identifiers), segments, rows


def _customer_column_metadata() -> list[dict[str, Any]]:
    # The two required columns are fixed by the accepted Task 2B schema.
    return [{"name": "client_id"}, {"name": "segment"}]


def _transaction_fields(metadata: dict[str, Any]) -> dict[str, str]:
    selected = identify_columns(metadata)
    fields = selected["transaction"]
    required = {
        "customer_reference",
        "date",
        "amount",
        "direction",
    }
    if not required <= set(fields):
        raise ValueError("Task 2B metadata does not identify all transaction fields")
    return fields


def _update_amount_summary(
    state: dict[str, Any],
    amounts: pa.Array,
) -> None:
    valid = amounts.drop_null()
    if not len(valid):
        return
    state["non_null_count"] += len(valid)
    minimum_maximum = pc.min_max(valid).as_py()
    if state["minimum"] is None or minimum_maximum["min"] < state["minimum"]:
        state["minimum"] = minimum_maximum["min"]
    if state["maximum"] is None or minimum_maximum["max"] > state["maximum"]:
        state["maximum"] = minimum_maximum["max"]
    state["zero_count"] += int(
        pc.sum(pc.cast(pc.equal(valid, 0), pa.int64())).as_py() or 0
    )
    state["negative_count"] += int(
        pc.sum(pc.cast(pc.less(valid, 0), pa.int64())).as_py() or 0
    )
    state["above_1000"] += int(
        pc.sum(pc.cast(pc.greater(valid, 1000), pa.int64())).as_py() or 0
    )
    state["above_5000"] += int(
        pc.sum(pc.cast(pc.greater(valid, 5000), pa.int64())).as_py() or 0
    )
    state["above_10000"] += int(
        pc.sum(pc.cast(pc.greater(valid, 10000), pa.int64())).as_py() or 0
    )

    remaining = max(0, SAMPLE_LIMIT - len(state["sample"]))
    if remaining:
        stride = max(1, math.ceil(len(valid) / remaining))
        indices = list(range(0, len(valid), stride))[:remaining]
        if indices:
            state["sample"].extend(
                valid.take(pa.array(indices, type=pa.int64())).to_pylist()
            )


def profile_transactions_by_customer(
    path: Path,
    metadata: dict[str, Any],
    customer_ids: list[Any],
    batch_size: int,
) -> dict[str, Any]:
    fields = _transaction_fields(metadata)
    customer_count = len(customer_ids)
    customer_id_array = pa.array(customer_ids)
    total_cells = customer_count * COMPLETE_WEEKS
    weekly_credits = array("d", [0.0]) * total_cells
    weekly_debits = array("d", [0.0]) * total_cells
    weekly_counts = array("I", [0]) * total_cells
    active_days = bytearray(customer_count * TOTAL_DAYS)

    transaction_counts = array("I", [0]) * customer_count
    credits_2024 = array("I", [0]) * customer_count
    debits_2024 = array("I", [0]) * customer_count
    credits_2025 = array("I", [0]) * customer_count
    debits_2025 = array("I", [0]) * customer_count
    active_day_counts = array("H", [0]) * customer_count
    first_days = array("h", [-1]) * customer_count
    last_days = array("h", [-1]) * customer_count

    amount_state: dict[str, Any] = {
        "non_null_count": 0,
        "minimum": None,
        "maximum": None,
        "zero_count": 0,
        "negative_count": 0,
        "above_1000": 0,
        "above_5000": 0,
        "above_10000": 0,
        "sample": [],
    }
    rows_scanned = 0
    orphan_rows = 0
    out_of_window_rows = 0
    partial_week_transactions = 0
    groups_processed = 0
    batches = 0
    peak_arrow_bytes = 0
    started = time.perf_counter()
    parquet_file = pq.ParquetFile(path)
    transaction_columns = [
        fields["customer_reference"],
        fields["date"],
        fields["amount"],
        fields["direction"],
    ]
    required_names = set(parquet_file.schema_arrow.names)
    missing = set(transaction_columns) - required_names
    if missing:
        raise ValueError(f"Transaction columns missing: {sorted(missing)}")

    study_start_scalar = pa.scalar(
        datetime(2024, 1, 1), type=pa.timestamp("ns")
    )
    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=transaction_columns,
    ):
        batches += 1
        rows_scanned += batch.num_rows
        references = batch.column(fields["customer_reference"])
        indices = pc.index_in(references, value_set=customer_id_array)
        valid_reference = pc.is_valid(indices)
        orphan_rows += int(
            pc.sum(
                pc.cast(pc.and_(pc.is_valid(references), pc.invert(valid_reference)), pa.int64())
            ).as_py()
            or 0
        )

        dates = batch.column(fields["date"])
        day_indices = pc.cast(
            pc.days_between(study_start_scalar, dates), pa.int32()
        )
        valid_window = pc.and_(
            pc.greater_equal(day_indices, 0),
            pc.less(day_indices, TOTAL_DAYS),
        )
        out_of_window_rows += int(
            pc.sum(pc.cast(pc.invert(valid_window), pa.int64())).as_py() or 0
        )
        valid = pc.and_(valid_reference, valid_window)
        if not bool(pc.any(valid).as_py()):
            continue

        customer_indices = pc.cast(indices.filter(valid), pa.int32())
        days = day_indices.filter(valid)
        amounts = batch.column(fields["amount"]).filter(valid)
        directions = batch.column(fields["direction"]).filter(valid)
        is_credit = pc.equal(directions, "C")
        is_debit = pc.equal(directions, "D")
        invalid_direction = int(
            pc.sum(
                pc.cast(pc.invert(pc.or_(is_credit, is_debit)), pa.int64())
            ).as_py()
            or 0
        )
        if invalid_direction:
            raise ValueError("Transaction direction contains unsupported values")

        credit_amounts = pc.if_else(is_credit, amounts, pa.scalar(0.0))
        debit_amounts = pc.if_else(is_debit, amounts, pa.scalar(0.0))
        credit_flags = pc.cast(is_credit, pa.uint32())
        debit_flags = pc.cast(is_debit, pa.uint32())
        _update_amount_summary(amount_state, amounts)

        grouped = pa.table(
            {
                "customer_index": customer_indices,
                "day_index": days,
                "credit_amount": credit_amounts,
                "debit_amount": debit_amounts,
                "credit_count": credit_flags,
                "debit_count": debit_flags,
            }
        ).group_by(["customer_index", "day_index"], use_threads=True).aggregate(
            [
                ("credit_amount", "sum"),
                ("debit_amount", "sum"),
                ("credit_count", "sum"),
                ("debit_count", "sum"),
            ]
        )
        grouped = grouped.sort_by(
            [
                ("customer_index", "ascending"),
                ("day_index", "ascending"),
            ]
        )
        columns = grouped.to_pydict()
        groups_processed += len(columns["customer_index"])
        for customer_index, day_index, credit_sum, debit_sum, credit_count, debit_count in zip(
            columns["customer_index"],
            columns["day_index"],
            columns["credit_amount_sum"],
            columns["debit_amount_sum"],
            columns["credit_count_sum"],
            columns["debit_count_sum"],
        ):
            count = int(credit_count + debit_count)
            transaction_counts[customer_index] += count
            if day_index < 366:
                credits_2024[customer_index] += int(credit_count)
                debits_2024[customer_index] += int(debit_count)
            else:
                credits_2025[customer_index] += int(credit_count)
                debits_2025[customer_index] += int(debit_count)

            daily_key = customer_index * TOTAL_DAYS + day_index
            if not active_days[daily_key]:
                active_days[daily_key] = 1
                active_day_counts[customer_index] += 1

            previous_first = first_days[customer_index]
            if previous_first < 0 or day_index < previous_first:
                first_days[customer_index] = day_index
            if day_index > last_days[customer_index]:
                last_days[customer_index] = day_index

            if day_index >= PARTIAL_WEEK_START_DAY:
                partial_week_transactions += count
                continue
            week_index = day_index // 7
            cell_index = customer_index * COMPLETE_WEEKS + week_index
            weekly_credits[cell_index] += credit_sum
            weekly_debits[cell_index] += debit_sum
            weekly_counts[cell_index] += count

        peak_arrow_bytes = max(peak_arrow_bytes, pa.total_allocated_bytes())
        if batches % 50 == 0:
            elapsed = time.perf_counter() - started
            print(
                f"Progress: batches={batches:,}, rows={rows_scanned:,}, "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )

    elapsed = time.perf_counter() - started
    return {
        "weekly_credits": weekly_credits,
        "weekly_debits": weekly_debits,
        "weekly_counts": weekly_counts,
        "transaction_counts": transaction_counts,
        "credits_2024": credits_2024,
        "debits_2024": debits_2024,
        "credits_2025": credits_2025,
        "debits_2025": debits_2025,
        "active_day_counts": active_day_counts,
        "first_days": first_days,
        "last_days": last_days,
        "rows_scanned": rows_scanned,
        "orphan_rows": orphan_rows,
        "out_of_window_rows": out_of_window_rows,
        "partial_week_transactions": partial_week_transactions,
        "groups_processed": groups_processed,
        "amount_state": amount_state,
        "execution": {
            "batches": batches,
            "batch_size": batch_size,
            "elapsed_seconds": round(elapsed, 6),
            "peak_arrow_allocated_bytes": peak_arrow_bytes,
        },
    }


def _summary_weekly_and_customer_activity(
    result: dict[str, Any],
    customer_count: int,
) -> dict[str, Any]:
    transaction_counts = result["transaction_counts"]
    active_day_counts = result["active_day_counts"]
    first_days = result["first_days"]
    last_days = result["last_days"]
    credits_2024 = result["credits_2024"]
    debits_2024 = result["debits_2024"]
    credits_2025 = result["credits_2025"]
    debits_2025 = result["debits_2025"]
    weekly_counts = result["weekly_counts"]
    weekly_credits = result["weekly_credits"]
    weekly_debits = result["weekly_debits"]

    active_customers = [
        index for index, count in enumerate(transaction_counts) if count > 0
    ]
    transaction_count_values = [int(value) for value in transaction_counts]
    active_transaction_counts = [
        int(transaction_counts[index]) for index in active_customers
    ]
    active_days_values = [
        int(active_day_counts[index]) for index in active_customers
    ]
    history_values = [
        int(last_days[index] - first_days[index] + 1)
        for index in active_customers
    ]
    active_weeks = array("H", [0]) * customer_count
    total_transactions_2024 = [
        int(credits_2024[index] + debits_2024[index])
        for index in range(customer_count)
    ]
    total_transactions_2025 = [
        int(credits_2025[index] + debits_2025[index])
        for index in range(customer_count)
    ]
    credit_counts_per_customer = [
        int(credits_2024[index] + credits_2025[index])
        for index in range(customer_count)
    ]
    debit_counts_per_customer = [
        int(debits_2024[index] + debits_2025[index])
        for index in range(customer_count)
    ]
    yearly_count_difference = [
        total_transactions_2025[index] - total_transactions_2024[index]
        for index in range(customer_count)
    ]

    active_weekly_counts: Counter[int] = Counter()
    observed_span_zero_weeks = 0
    active_cells = 0
    inactive_cells = 0
    net_minimum: float | None = None
    net_maximum: float | None = None
    net_sum = 0.0
    negative_net_weeks = 0
    zero_net_weeks = 0
    positive_net_weeks = 0
    weekly_net_cells: array[float] = array("d")

    for customer_index in range(customer_count):
        base = customer_index * COMPLETE_WEEKS
        customer_active_weeks = 0
        for week_index in range(COMPLETE_WEEKS):
            cell = base + week_index
            count = weekly_counts[cell]
            net = weekly_credits[cell] - weekly_debits[cell]
            if count:
                active_cells += 1
                customer_active_weeks += 1
                active_weekly_counts[count] += 1
                if net < 0:
                    negative_net_weeks += 1
                elif net == 0:
                    zero_net_weeks += 1
                else:
                    positive_net_weeks += 1
                net_sum += net
                net_minimum = net if net_minimum is None else min(net_minimum, net)
                net_maximum = net if net_maximum is None else max(net_maximum, net)
                weekly_net_cells.append(net)
            else:
                inactive_cells += 1
        active_weeks[customer_index] = customer_active_weeks

        if transaction_counts[customer_index] > 0:
            first_week = min(
                COMPLETE_WEEKS - 1, max(0, first_days[customer_index] // 7)
            )
            last_week = min(
                COMPLETE_WEEKS - 1, max(0, last_days[customer_index] // 7)
            )
            observed_span_zero_weeks += (
                max(0, last_week - first_week + 1) - customer_active_weeks
            )

    active_net_sample = list(
        weekly_net_cells[:: max(1, math.ceil(len(weekly_net_cells) / SAMPLE_LIMIT))]
    )
    active_week_distribution = _weighted_distribution(active_weekly_counts)
    credit_debit_profile = Counter()
    for index in range(customer_count):
        credit_count = credits_2024[index] + credits_2025[index]
        debit_count = debits_2024[index] + debits_2025[index]
        if not credit_count and not debit_count:
            credit_debit_profile["no_transactions"] += 1
        elif credit_count and debit_count:
            credit_debit_profile["credit_and_debit"] += 1
        elif credit_count:
            credit_debit_profile["credit_only"] += 1
        else:
            credit_debit_profile["debit_only"] += 1

    yearly_comparison = Counter()
    for index in range(customer_count):
        count_2024 = total_transactions_2024[index]
        count_2025 = total_transactions_2025[index]
        if count_2024 == 0 and count_2025 == 0:
            direction = "inactive_both_years"
        elif count_2024 == 0:
            direction = "active_2025_only"
        elif count_2025 == 0:
            direction = "active_2024_only"
        elif count_2025 > count_2024:
            direction = "more_transactions_2025"
        elif count_2025 < count_2024:
            direction = "fewer_transactions_2025"
        else:
            direction = "equal_transactions"
        yearly_comparison[direction] += 1

    active_both_years = sum(
        int(total_transactions_2024[index] > 0 and total_transactions_2025[index] > 0)
        for index in range(customer_count)
    )
    first_active_day = min(
        (first_days[index] for index in active_customers), default=None
    )
    last_active_day = max(
        (last_days[index] for index in active_customers), default=None
    )
    return {
        "customer_count": customer_count,
        "active_customer_count": len(active_customers),
        "zero_transaction_customer_count": customer_count - len(active_customers),
        "transactions_per_customer_all": _distribution(transaction_count_values),
        "transactions_per_customer_active": _distribution(active_transaction_counts),
        "active_days_per_customer": _distribution(active_days_values),
        "history_days_per_active_customer": _distribution(history_values),
        "first_transaction_date_distribution": _day_index_distribution(
            [int(first_days[index]) for index in active_customers]
        ),
        "last_transaction_date_distribution": _day_index_distribution(
            [int(last_days[index]) for index in active_customers]
        ),
        "active_weeks_per_customer": _distribution(
            [int(active_weeks[index]) for index in active_customers]
        ),
        "calendar_weeks_per_customer": COMPLETE_WEEKS,
        "active_customer_weeks": active_cells,
        "zero_activity_customer_weeks_in_full_window": inactive_cells,
        "zero_activity_weeks_within_observed_spans": observed_span_zero_weeks,
        "weekly_transaction_count_distribution_on_active_weeks": active_week_distribution,
        "weekly_net_cash_flow_active_weeks": {
            **_sample_distribution(active_net_sample),
            "active_week_count": active_cells,
            "negative_week_count": negative_net_weeks,
            "zero_week_count": zero_net_weeks,
            "positive_week_count": positive_net_weeks,
            "exact_minimum": net_minimum,
            "exact_maximum": net_maximum,
            "exact_mean": net_sum / active_cells if active_cells else None,
        },
        "credit_debit_customer_profile": dict(credit_debit_profile),
        "credit_transactions_per_customer": _distribution(
            credit_counts_per_customer
        ),
        "debit_transactions_per_customer": _distribution(
            debit_counts_per_customer
        ),
        "customers_active_in_both_years": active_both_years,
        "yearly_activity_comparison": dict(yearly_comparison),
        "yearly_transaction_count_difference_2025_minus_2024": _distribution(
            yearly_count_difference
        ),
        "transaction_totals_by_year": {
            "2024": sum(total_transactions_2024),
            "2025": sum(total_transactions_2025),
        },
        "first_transaction_date_across_customers": (
            (STUDY_START + timedelta(days=first_active_day)).isoformat()
            if first_active_day is not None
            else None
        ),
        "last_transaction_date_across_customers": (
            (STUDY_START + timedelta(days=last_active_day)).isoformat()
            if last_active_day is not None
            else None
        ),
        "_active_weeks": active_weeks,
        "_history_values": history_values,
        "_transaction_counts": transaction_count_values,
        "_active_both_years": [
            bool(total_transactions_2024[index] > 0 and total_transactions_2025[index] > 0)
            for index in range(customer_count)
        ],
    }


def _eligibility_sensitivity(summary: dict[str, Any]) -> dict[str, Any]:
    transaction_counts = summary["_transaction_counts"]
    active_weeks = summary["_active_weeks"]
    history_days = array(
        "h",
        [
            (
                summary["_history_values"][index]
                if index < len(summary["_history_values"])
                else 0
            )
            for index in range(len(transaction_counts))
        ],
    )
    # Reconstruct active-customer history by using the active-week mask.
    active_mask = [
        transaction_counts[index] > 0
        for index in range(len(transaction_counts))
    ]
    history_active_index = 0
    for index, active in enumerate(active_mask):
        if active:
            history_days[index] = summary["_history_values"][history_active_index]
            history_active_index += 1
        else:
            history_days[index] = 0
    both_years = summary["_active_both_years"]

    transaction_sensitivity = [
        {
            "minimum": threshold,
            "customer_count": sum(
                count >= threshold for count in transaction_counts
            ),
        }
        for threshold in WEEKLY_COUNT_THRESHOLDS
    ]
    week_sensitivity = [
        {
            "minimum_active_weeks": threshold,
            "customer_count": sum(
                1
                for index, count in enumerate(transaction_counts)
                if count > 0 and active_weeks[index] >= threshold
            ),
        }
        for threshold in ACTIVE_WEEK_THRESHOLDS
    ]
    history_sensitivity = [
        {
            "minimum_history_days": threshold,
            "customer_count": sum(
                1
                for index, count in enumerate(transaction_counts)
                if count > 0 and history_days[index] >= threshold
            ),
        }
        for threshold in HISTORY_DAY_THRESHOLDS
    ]

    recommended = [
        index
        for index in range(len(transaction_counts))
        if transaction_counts[index] >= RECOMMENDED_ELIGIBILITY["minimum_transactions"]
        and active_weeks[index] >= RECOMMENDED_ELIGIBILITY["minimum_active_weeks"]
        and history_days[index] >= RECOMMENDED_ELIGIBILITY["minimum_history_days"]
        and (
            both_years[index]
            or not RECOMMENDED_ELIGIBILITY["active_in_both_years"]
        )
    ]
    joint_sensitivity = []
    for transaction_minimum in (10, 50, 100, 200):
        for week_minimum in (12, 26, 52):
            count = sum(
                1
                for index, transaction_count in enumerate(transaction_counts)
                if transaction_count >= transaction_minimum
                and active_weeks[index] >= week_minimum
                and history_days[index] >= 180
                and both_years[index]
            )
            joint_sensitivity.append(
                {
                    "minimum_transactions": transaction_minimum,
                    "minimum_active_weeks": week_minimum,
                    "minimum_history_days": 180,
                    "active_in_both_years": True,
                    "customer_count": count,
                }
            )

    return {
        "all_private_customers": len(transaction_counts),
        "transaction_count_sensitivity": transaction_sensitivity,
        "active_week_sensitivity": week_sensitivity,
        "history_length_sensitivity": history_sensitivity,
        "joint_sensitivity": joint_sensitivity,
        "recommended_eligibility": {
            **RECOMMENDED_ELIGIBILITY,
            "eligible_customer_count": len(recommended),
            "excluded_customer_count": len(transaction_counts) - len(recommended),
            "status": "provisional_specification_not_applied_to_model",
        },
    }


def build_analysis(
    dataset_dir: Path,
    metadata_path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    metadata = _load_metadata(metadata_path)
    customer_path = dataset_dir / "customers.parquet"
    transaction_path = dataset_dir / "transactions.parquet"
    if not customer_path.is_file() or not transaction_path.is_file():
        raise ValueError("Required customers and transactions files are missing")

    customer_ids, segment_counts, customer_rows = load_customer_universe(
        customer_path
    )
    transaction_result = profile_transactions_by_customer(
        transaction_path,
        metadata,
        customer_ids,
        batch_size,
    )
    summary = _summary_weekly_and_customer_activity(
        transaction_result, len(customer_ids)
    )
    eligibility = _eligibility_sensitivity(summary)

    active_weeks = summary.pop("_active_weeks")
    history_values = summary.pop("_history_values")
    transaction_counts = summary.pop("_transaction_counts")
    summary.pop("_active_both_years")
    amount_state = transaction_result["amount_state"]
    amount_samples = amount_state.pop("sample")
    amount_sample = list(
        amount_samples[
            :: max(1, math.ceil(len(amount_samples) / SAMPLE_LIMIT))
        ]
    )

    return {
        "report_schema_version": "1.0",
        "analysis_mode": "customer_distribution_discovery",
        "pyarrow_version": pa.__version__,
        "dataset_name": dataset_dir.name,
        "customer_file": {
            "row_count": customer_rows,
            "identifier_count": len(customer_ids),
            "segment_counts": [
                {"value": value, "count": count}
                for value, count in sorted(
                    segment_counts.items(),
                    key=lambda item: (item[0] is None, str(item[0])),
                )
            ],
        },
        "calendar_definition": {
            "study_start": STUDY_START.isoformat(),
            "study_end": STUDY_END.isoformat(),
            "week_start": "Monday",
            "complete_week_count": COMPLETE_WEEKS,
            "complete_week_end": (
                STUDY_START + timedelta(days=COMPLETE_WEEKS * 7 - 1)
            ).isoformat(),
            "partial_week_excluded_from_target": True,
            "partial_week_start": (
                STUDY_START + timedelta(days=PARTIAL_WEEK_START_DAY)
            ).isoformat(),
            "partial_week_end": STUDY_END.isoformat(),
            "partial_week_transaction_count": transaction_result[
                "partial_week_transactions"
            ],
        },
        "transaction_scan": {
            "rows_scanned": transaction_result["rows_scanned"],
            "orphan_customer_rows": transaction_result["orphan_rows"],
            "out_of_window_rows": transaction_result["out_of_window_rows"],
            "customer_day_groups_processed": transaction_result[
                "groups_processed"
            ],
            "execution": transaction_result["execution"],
        },
        "amount_distribution": {
            **_sample_distribution(amount_sample),
            "non_null_count": amount_state["non_null_count"],
            "exact_minimum": amount_state["minimum"],
            "exact_maximum": amount_state["maximum"],
            "zero_count": amount_state["zero_count"],
            "negative_count": amount_state["negative_count"],
            "above_1000_count": amount_state["above_1000"],
            "above_5000_count": amount_state["above_5000"],
            "above_10000_count": amount_state["above_10000"],
        },
        "customer_activity": summary,
        "eligibility_sensitivity": eligibility,
        "recommended_feature_groups": {
            "target_lags": ["lag_1_net", "lag_2_net", "lag_4_net", "lag_8_net"],
            "rolling_history": [
                "rolling_2_week_mean",
                "rolling_4_week_mean",
                "rolling_8_week_mean",
                "rolling_8_week_std",
                "credit_sum_windows",
                "debit_sum_windows",
                "active_day_count",
            ],
            "calendar": ["week_of_year", "month"],
            "excluded_from_initial_pipeline": ["account_balance_features", "SME_label"],
        },
        "limitations": [
            "Zero transaction activity is treated as zero observed activity, not "
            "automatically as missing source data.",
            "Weekly net-flow quantiles use a deterministic bounded sample; exact "
            "sign counts, sums and extrema are retained.",
            "Exact transaction identifier uniqueness and counterparty-account "
            "distinctness remain deferred because their identifier spaces are "
            "unbounded for bounded-memory processing.",
            "The final weekly panel, eligibility assignment, split assignment, "
            "preprocessing pipeline and models have not been created.",
            "Synthetic data cannot establish performance on real customers.",
        ],
        "_customer_metric_arrays": {
            "active_weeks": active_weeks,
            "history_values": history_values,
            "transaction_counts": transaction_counts,
        },
    }


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.4f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _distribution_table(label: str, distribution: dict[str, Any]) -> list[str]:
    return [
        f"| {label} | {_format_number(distribution['count'])} | "
        f"{_format_number(distribution['minimum'])} | "
        f"{_format_number(distribution['median'])} | "
        f"{_format_number(distribution['mean'])} | "
        f"{_format_number(distribution['p90'])} | "
        f"{_format_number(distribution['p95'])} | "
        f"{_format_number(distribution['p99'])} | "
        f"{_format_number(distribution['maximum'])} |"
    ]


def render_markdown(report: dict[str, Any]) -> str:
    customer = report["customer_activity"]
    eligibility = report["eligibility_sensitivity"]["recommended_eligibility"]
    amount = report["amount_distribution"]
    weekly = customer["weekly_net_cash_flow_active_weeks"]
    lines = [
        "# Customer Distribution and Activity Analysis",
        "",
        "## Executive Summary",
        "",
        (
            f"The customer universe contains {customer['customer_count']:,} "
            f"customers, of which {customer['active_customer_count']:,} have "
            f"at least one transaction and "
            f"{customer['zero_transaction_customer_count']:,} have none. "
            f"A provisional eligibility rule identifies "
            f"{eligibility['eligible_customer_count']:,} customers for later "
            "panel construction; no customer has yet been assigned to a model "
            "partition."
        ),
        "",
        (
            "The analysis uses complete Monday-to-Sunday weeks. The final "
            "partial week is excluded from target and feature generation, while "
            "its transactions are reported separately."
        ),
        "",
        "## Customer Activity Distributions",
        "",
        "| Measure | Customers/weeks | Min | Median | Mean | P90 | P95 | P99 | Max |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        _distribution_table(
            "Transactions per customer (all)", customer["transactions_per_customer_all"]
        )
    )
    lines.extend(
        _distribution_table(
            "Transactions per active customer",
            customer["transactions_per_customer_active"],
        )
    )
    lines.extend(
        _distribution_table(
            "Active transaction days", customer["active_days_per_customer"]
        )
    )
    lines.extend(
        _distribution_table(
            "Observed history days", customer["history_days_per_active_customer"]
        )
    )
    lines.extend(
        _distribution_table(
            "Active complete weeks", customer["active_weeks_per_customer"]
        )
    )
    lines.extend(
        _distribution_table(
            "Credit transactions per customer",
            customer["credit_transactions_per_customer"],
        )
    )
    lines.extend(
        _distribution_table(
            "Debit transactions per customer",
            customer["debit_transactions_per_customer"],
        )
    )
    lines.extend(
        [
            "",
            "The observed history length is the inclusive number of calendar "
            "days between a customer's first and last transaction. Active "
            "weeks count only Monday-to-Sunday periods containing at least one "
            "transaction.",
            "",
            "### First and last transaction dates",
            "",
            "| Measure | Earliest | P05 | Median | P95 | Latest | Distinct dates |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
            (
                "| First transaction date | "
                f"{customer['first_transaction_date_distribution']['minimum_date']} | "
                f"{customer['first_transaction_date_distribution']['p05_date']} | "
                f"{customer['first_transaction_date_distribution']['median_date']} | "
                f"{customer['first_transaction_date_distribution']['p95_date']} | "
                f"{customer['first_transaction_date_distribution']['maximum_date']} | "
                f"{customer['first_transaction_date_distribution']['distinct_dates']:,} |"
            ),
            (
                "| Last transaction date | "
                f"{customer['last_transaction_date_distribution']['minimum_date']} | "
                f"{customer['last_transaction_date_distribution']['p05_date']} | "
                f"{customer['last_transaction_date_distribution']['median_date']} | "
                f"{customer['last_transaction_date_distribution']['p95_date']} | "
                f"{customer['last_transaction_date_distribution']['maximum_date']} | "
                f"{customer['last_transaction_date_distribution']['distinct_dates']:,} |"
            ),
            "",
            "## Calendar and Weekly Activity",
            "",
            f"- Complete calendar weeks per customer: "
            f"{customer['calendar_weeks_per_customer']:,}.",
            f"- Active customer-weeks: {customer['active_customer_weeks']:,}.",
            f"- Zero-activity customer-weeks in the full window: "
            f"{customer['zero_activity_customer_weeks_in_full_window']:,}.",
            f"- Zero-activity weeks within each customer's observed span: "
            f"{customer['zero_activity_weeks_within_observed_spans']:,}.",
            f"- Partial-week transactions excluded from targets/features: "
            f"{report['calendar_definition']['partial_week_transaction_count']:,}.",
            "",
            "Zero-activity weeks are retained as observed zero activity. They "
            "are not automatically labelled missing source data.",
            "",
            "| Weekly active-cell measure | Count | Min | Median | Mean | P90 | P95 | P99 | Max |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        _distribution_table(
            "Transactions per active customer-week",
            customer["weekly_transaction_count_distribution_on_active_weeks"],
        )
    )
    lines.extend(
        [
            "",
            "## Weekly Net Cash-Flow Distribution",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| Active customer-weeks | {weekly['active_week_count']:,} |",
            f"| Negative net-flow weeks | {weekly['negative_week_count']:,} |",
            f"| Zero net-flow active weeks | {weekly['zero_week_count']:,} |",
            f"| Positive net-flow weeks | {weekly['positive_week_count']:,} |",
            f"| Exact minimum (EUR) | {_format_number(weekly['exact_minimum'])} |",
            f"| Exact maximum (EUR) | {_format_number(weekly['exact_maximum'])} |",
            f"| Exact mean (EUR) | {_format_number(weekly['exact_mean'])} |",
            f"| Sampled p25 (EUR) | {_format_number(weekly['p25'])} |",
            f"| Sampled median (EUR) | {_format_number(weekly['median'])} |",
            f"| Sampled p75 (EUR) | {_format_number(weekly['p75'])} |",
            f"| Sampled p95 (EUR) | {_format_number(weekly['p95'])} |",
            f"| Sampled p99 (EUR) | {_format_number(weekly['p99'])} |",
            "",
            "Quantiles use a deterministic systematic sample. Sign counts, "
            "sums and extrema are exact aggregates.",
            "",
            "## Credit and Debit Activity",
            "",
            f"- Customers with both credits and debits: "
            f"{customer['credit_debit_customer_profile'].get('credit_and_debit', 0):,}.",
            f"- Credit-only customers: "
            f"{customer['credit_debit_customer_profile'].get('credit_only', 0):,}.",
            f"- Debit-only customers: "
            f"{customer['credit_debit_customer_profile'].get('debit_only', 0):,}.",
            f"- Customers with no transactions: "
            f"{customer['credit_debit_customer_profile'].get('no_transactions', 0):,}.",
            f"- Customers active in both 2024 and 2025: "
            f"{customer['customers_active_in_both_years']:,}.",
            f"- 2024 transactions: "
            f"{customer['transaction_totals_by_year']['2024']:,}; 2025 "
            f"transactions: {customer['transaction_totals_by_year']['2025']:,}.",
            "",
            "### Year-over-year activity changes",
            "",
            "| Activity pattern | Customers |",
            "| --- | ---: |",
        ]
    )
    for key, value in sorted(customer["yearly_activity_comparison"].items()):
        lines.append(f"| `{key}` | {value:,} |")
    difference = customer["yearly_transaction_count_difference_2025_minus_2024"]
    lines.extend(
        [
            "",
            "The per-customer difference in transaction count (2025 minus 2024) "
            f"has median {_format_number(difference['median'])} and range "
            f"{_format_number(difference['minimum'])} to "
            f"{_format_number(difference['maximum'])}.",
        ]
    )

    lines.extend(
        [
            "",
            "## Transaction Amount Extremes",
            "",
            f"- Non-null transactions: {amount['non_null_count']:,}.",
            f"- Exact amount range: EUR {_format_number(amount['exact_minimum'])} "
            f"to {_format_number(amount['exact_maximum'])}.",
            f"- Zero amounts: {amount['zero_count']:,}; negative amounts: "
            f"{amount['negative_count']:,}.",
            f"- Amounts above EUR 1,000: {amount['above_1000_count']:,}.",
            f"- Amounts above EUR 5,000: {amount['above_5000_count']:,}.",
            f"- Amounts above EUR 10,000: {amount['above_10000_count']:,}.",
            f"- Sampled p99 amount: EUR {_format_number(amount['p99'])}.",
            "",
            "Extreme values are reported but are not clipped or removed. The "
            "target retains actual cash-flow semantics; any robust treatment "
            "would require a separately validated rule.",
            "",
            "## Eligibility Sensitivity",
            "",
            "| Minimum transactions | Eligible customers |",
            "| ---: | ---: |",
        ]
    )
    for item in report["eligibility_sensitivity"]["transaction_count_sensitivity"]:
        lines.append(
            f"| {item['minimum']:,} | {item['customer_count']:,} |"
        )

    lines.extend(
        [
            "",
            "| Minimum active weeks | Eligible customers |",
            "| ---: | ---: |",
        ]
    )
    for item in report["eligibility_sensitivity"]["active_week_sensitivity"]:
        lines.append(
            f"| {item['minimum_active_weeks']:,} | "
            f"{item['customer_count']:,} |"
        )

    lines.extend(
        [
            "",
            "| Minimum observed history (days) | Eligible customers |",
            "| ---: | ---: |",
        ]
    )
    for item in report["eligibility_sensitivity"]["history_length_sensitivity"]:
        lines.append(
            f"| {item['minimum_history_days']:,} | "
            f"{item['customer_count']:,} |"
        )

    lines.extend(
        [
            "",
            "### Recommended provisional rule",
            "",
            f"- At least {eligibility['minimum_transactions']:,} transactions.",
            f"- At least {eligibility['minimum_active_weeks']:,} active weeks.",
            f"- At least {eligibility['minimum_history_days']:,} observed "
            "calendar days.",
            "- Activity in both 2024 and 2025.",
            f"- Eligible customers: {eligibility['eligible_customer_count']:,} "
            f"of {report['eligibility_sensitivity']['all_private_customers']:,}.",
            "",
            "This rule is a specification for later panel construction and has "
            "not been applied to any model or output dataset.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "Raw customer identifiers and transaction records are not included.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    report: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    public_report = copy.deepcopy(report)
    public_report.pop("_customer_metric_arrays", None)
    execution = public_report["transaction_scan"]["execution"]
    execution.pop("elapsed_seconds", None)
    execution.pop("peak_arrow_allocated_bytes", None)
    json_path.write_text(
        json.dumps(
            public_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_path.write_text(
        render_markdown(public_report), encoding="utf-8", newline="\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyse customer-level transaction and weekly cash-flow "
            "distributions without creating the final modelling panel."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--metadata-report", type=Path, default=METADATA_REPORT)
    parser.add_argument("--json-report", type=Path, default=JSON_REPORT)
    parser.add_argument("--markdown-report", type=Path, default=MARKDOWN_REPORT)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.batch_size <= 0:
            raise ValueError("Batch size must be positive")
        dataset = args.dataset_dir.resolve()
        for report_path in (args.json_report, args.markdown_report):
            if report_path.resolve().is_relative_to(dataset):
                raise ValueError("Report output must be outside the source dataset")
        report = build_analysis(
            args.dataset_dir, args.metadata_report, batch_size=args.batch_size
        )
        write_reports(report, args.json_report, args.markdown_report)
    except (OSError, ValueError, json.JSONDecodeError, pa.ArrowException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    activity = report["customer_activity"]
    print(f"Customers: {activity['customer_count']}")
    print(f"Active customers: {activity['active_customer_count']}")
    print(
        "Recommended eligible customers: "
        f"{report['eligibility_sensitivity']['recommended_eligibility']['eligible_customer_count']}"
    )
    print(
        "Transaction scan elapsed seconds: "
        f"{report['transaction_scan']['execution']['elapsed_seconds']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
