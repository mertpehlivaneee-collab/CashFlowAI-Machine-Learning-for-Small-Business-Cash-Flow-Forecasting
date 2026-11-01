#!/usr/bin/env python3
"""Inspect CashFlowAI archive metadata without extracting members.

The inventory is intentionally limited to archive metadata. It does not read
member contents, inspect Parquet schemas, or make claims about data tables.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence


DICTIONARY_NAME = "DATA_DICTIONARY.html"
DEFAULT_REPORT = Path("reports/data_inspection/archive_inventory.md")
REGULAR_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE})
ALLOWED_TYPES = REGULAR_TYPES | {tarfile.DIRTYPE}
MEMBER_TYPE_NAMES = {
    tarfile.REGTYPE: "regular file",
    tarfile.AREGTYPE: "regular file (legacy)",
    tarfile.DIRTYPE: "directory",
    tarfile.SYMTYPE: "symbolic link",
    tarfile.LNKTYPE: "hard link",
    tarfile.CHRTYPE: "character device",
    tarfile.BLKTYPE: "block device",
    tarfile.FIFOTYPE: "FIFO",
    tarfile.CONTTYPE: "contiguous file",
}


@dataclass(frozen=True, slots=True)
class MemberRecord:
    """Sanitised metadata for one archive member."""

    index: int
    name: str
    member_type: str
    size: int
    mode: int
    link_name: str
    warnings: tuple[str, ...]
    is_dictionary: bool


@dataclass(frozen=True, slots=True)
class ArchiveInventory:
    """Metadata-only summary of an archive."""

    archive_name: str
    archive_size: int
    members: tuple[MemberRecord, ...]

    @property
    def dictionary_members(self) -> tuple[MemberRecord, ...]:
        return tuple(member for member in self.members if member.is_dictionary)

    @property
    def total_uncompressed_size(self) -> int:
        return sum(member.size for member in self.members)

    @property
    def warning_count(self) -> int:
        return sum(len(member.warnings) for member in self.members)


def _path_warnings(path: str) -> list[str]:
    """Return deterministic safety warnings for an archive path or link target."""

    if not path:
        return ["path is empty"]
    if "\x00" in path:
        return ["path contains a NUL byte"]

    warnings: list[str] = []
    if PurePosixPath(path).is_absolute():
        warnings.append("absolute path")

    windows_path = PureWindowsPath(path)
    if windows_path.drive:
        warnings.append("path contains a Windows drive")
    elif windows_path.is_absolute():
        warnings.append("Windows absolute path")

    if any(part == ".." for part in re.split(r"[/\\]", path)):
        warnings.append("parent-directory traversal")
    if "\\" in path:
        warnings.append("backslash in archive path")

    return warnings


def _member_type_name(member: tarfile.TarInfo) -> str:
    known_name = MEMBER_TYPE_NAMES.get(member.type)
    if known_name is not None:
        return known_name
    return f"unexpected type ({member.type!r})"


def _basename(path: str) -> str:
    return re.split(r"[/\\]", path.rstrip("/\\"))[-1]


def _inspect_member(member: tarfile.TarInfo, index: int) -> MemberRecord:
    warnings = [f"member path: {warning}" for warning in _path_warnings(member.name)]
    member_type = _member_type_name(member)

    if member.type == tarfile.SYMTYPE:
        warnings.append("symbolic-link members are not allowed")
    elif member.type == tarfile.LNKTYPE:
        warnings.append("hard-link members are not allowed")
    elif member.type not in ALLOWED_TYPES:
        warnings.append(f"unexpected member type: {member_type}")

    if member.type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
        warnings.extend(
            f"link target: {warning}" for warning in _path_warnings(member.linkname)
        )

    if member.size < 0:
        warnings.append("member has a negative size")
    if member.type not in {tarfile.DIRTYPE} and re.search(r"[/\\]$", member.name):
        warnings.append("non-directory path ends with a separator")

    is_dictionary = (
        member.type in REGULAR_TYPES and _basename(member.name) == DICTIONARY_NAME
    )
    return MemberRecord(
        index=index,
        name=member.name,
        member_type=member_type,
        size=member.size,
        mode=member.mode & 0o7777,
        link_name=member.linkname,
        warnings=tuple(warnings),
        is_dictionary=is_dictionary,
    )


def scan_archive(archive_path: Path) -> ArchiveInventory:
    """Read archive member metadata without extracting any member."""

    with tarfile.open(archive_path, mode="r:*") as archive:
        tar_members = archive.getmembers()

    records = [_inspect_member(member, index) for index, member in enumerate(tar_members)]
    name_counts = Counter(record.name for record in records)
    records = [
        replace(
            record,
            warnings=record.warnings + ("duplicate member path",)
            if name_counts[record.name] > 1
            else record.warnings,
        )
        for record in records
    ]
    records.sort(key=lambda record: (record.name, record.index))

    return ArchiveInventory(
        archive_name=archive_path.name,
        archive_size=archive_path.stat().st_size,
        members=tuple(records),
    )


def _markdown_cell(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def render_report(inventory: ArchiveInventory) -> str:
    """Render a deterministic Markdown inventory without local paths."""

    regular_count = sum(
        member.member_type in {"regular file", "regular file (legacy)"}
        for member in inventory.members
    )
    directory_count = sum(
        member.member_type == "directory" for member in inventory.members
    )
    warning_summary = (
        "No safety warnings detected."
        if inventory.warning_count == 0
        else f"{inventory.warning_count} safety warning(s) detected."
    )

    lines = [
        "# Synthetic Banking Archive Inventory",
        "",
        "This deterministic report lists archive metadata only. It was generated "
        "without extracting archive members or reading member contents.",
        "",
        "## Summary",
        "",
        "| Property | Value |",
        "| --- | ---: |",
        f"| Archive | `{_markdown_cell(inventory.archive_name)}` |",
        f"| Compressed size (bytes) | {inventory.archive_size:,} |",
        f"| Members | {len(inventory.members):,} |",
        f"| Directories | {directory_count:,} |",
        f"| Regular files | {regular_count:,} |",
        f"| Total member size (bytes) | {inventory.total_uncompressed_size:,} |",
        f"| Safety warnings | {inventory.warning_count:,} |",
        "",
        f"Status: {warning_summary}",
        "",
        "## Data Dictionary",
        "",
    ]

    if inventory.dictionary_members:
        lines.extend(
            [
                "| Full archive path | Size (bytes) |",
                "| --- | ---: |",
            ]
        )
        lines.extend(
            f"| {_markdown_cell(member.name)} | {member.size:,} |"
            for member in inventory.dictionary_members
        )
    else:
        lines.append(
            f"No regular file named exactly `{DICTIONARY_NAME}` was found."
        )

    lines.extend(
        [
            "",
            "The dictionary was located by exact basename only. This inventory "
            "does not parse its contents or infer schema relationships.",
            "",
            "## Safety Checks",
            "",
            "The inventory checks for absolute or traversal paths, Windows drive "
            "paths, backslashes, empty or NUL-containing paths, symbolic links, "
            "hard links, unexpected member types, negative sizes and duplicate "
            "member paths.",
            "",
        ]
    )

    if inventory.warning_count:
        lines.extend(
            [
                "| Full archive path | Warnings |",
                "| --- | --- |",
            ]
        )
        for member in inventory.members:
            if member.warnings:
                warnings = "; ".join(
                    _markdown_cell(warning) for warning in member.warnings
                )
                lines.append(f"| {_markdown_cell(member.name)} | {warnings} |")
    else:
        lines.append(
            "No unsafe paths, links, unexpected member types or duplicate paths "
            "were detected."
        )

    lines.extend(
        [
            "",
            "## Members",
            "",
            "| # | Full archive path | Type | Size (bytes) | Mode | Link target | Warnings |",
            "| ---: | --- | --- | ---: | --- | --- | --- |",
        ]
    )

    for number, member in enumerate(inventory.members, start=1):
        warnings = "; ".join(member.warnings) if member.warnings else "None"
        lines.append(
            "| "
            f"{number} | {_markdown_cell(member.name)} | "
            f"{_markdown_cell(member.member_type)} | {member.size:,} | "
            f"{member.mode:04o} | {_markdown_cell(member.link_name) or 'None'} | "
            f"{_markdown_cell(warnings)} |"
        )

    return "\n".join(lines) + "\n"


def write_report(report_path: Path, report: str) -> None:
    """Write the generated report with deterministic UTF-8 line endings."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a read-only, metadata-only inventory of a tar archive "
            "without extracting its members."
        )
    )
    parser.add_argument("archive", type=Path, help="Path to the tar archive")
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Markdown output path (default: {DEFAULT_REPORT.as_posix()})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        inventory = scan_archive(args.archive)
        write_report(args.report, render_report(inventory))
    except (OSError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    dictionaries = inventory.dictionary_members
    dictionary_summary = (
        f"{dictionaries[0].name} ({dictionaries[0].size:,} bytes)"
        if len(dictionaries) == 1
        else f"{len(dictionaries)} matches"
    )
    print(f"Archive: {inventory.archive_name}")
    print(f"Members: {len(inventory.members)}")
    print(f"Dictionary: {dictionary_summary}")
    print(f"Safety warnings: {inventory.warning_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
