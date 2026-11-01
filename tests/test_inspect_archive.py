"""Tests for the read-only archive inventory CLI."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

from scripts import inspect_archive


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "inspect_archive.py"


def add_bytes(
    archive: tarfile.TarFile,
    name: str,
    data: bytes = b"content",
) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = 0o644
    archive.addfile(member, io.BytesIO(data))


def add_directory(archive: tarfile.TarFile, name: str) -> None:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = 0o755
    archive.addfile(member)


def make_safe_archive(path: Path) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        add_directory(archive, "student_export")
        add_bytes(archive, "student_export/customers.parquet", b"metadata-only")
        add_bytes(
            archive,
            "student_export/DATA_DICTIONARY.html",
            b"<html><body>Dictionary</body></html>",
        )


def test_scan_safe_archive_and_locate_dictionary(tmp_path: Path) -> None:
    archive_path = tmp_path / "safe.tar.gz"
    make_safe_archive(archive_path)

    inventory = inspect_archive.scan_archive(archive_path)

    assert inventory.archive_name == "safe.tar.gz"
    assert [member.name for member in inventory.members] == [
        "student_export",
        "student_export/DATA_DICTIONARY.html",
        "student_export/customers.parquet",
    ]
    assert inventory.members[0].member_type == "directory"
    assert inventory.members[2].member_type == "regular file"
    assert inventory.warning_count == 0
    assert [
        (member.name, member.size) for member in inventory.dictionary_members
    ] == [("student_export/DATA_DICTIONARY.html", 36)]


def test_detects_unsafe_absolute_and_traversal_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-paths.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        add_bytes(archive, "../escape.txt")
        add_bytes(archive, "/absolute.txt")
        add_bytes(archive, r"C:\drive.txt")
        add_bytes(archive, r"nested\..\escape.txt")

    inventory = inspect_archive.scan_archive(archive_path)
    warnings = {member.name: member.warnings for member in inventory.members}

    assert "member path: parent-directory traversal" in warnings["../escape.txt"]
    assert "member path: absolute path" in warnings["/absolute.txt"]
    assert "member path: path contains a Windows drive" in warnings[
        r"C:\drive.txt"
    ]
    assert "member path: parent-directory traversal" in warnings[
        r"nested\..\escape.txt"
    ]


def test_detects_links_and_unexpected_member_types(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-types.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        add_bytes(archive, "target.txt")

        symbolic = tarfile.TarInfo("symbolic-link")
        symbolic.type = tarfile.SYMTYPE
        symbolic.linkname = "../../outside.txt"
        archive.addfile(symbolic)

        hard = tarfile.TarInfo("hard-link")
        hard.type = tarfile.LNKTYPE
        hard.linkname = "target.txt"
        archive.addfile(hard)

        fifo = tarfile.TarInfo("device.fifo")
        fifo.type = tarfile.FIFOTYPE
        archive.addfile(fifo)

    inventory = inspect_archive.scan_archive(archive_path)
    warnings = {member.name: member.warnings for member in inventory.members}

    assert "symbolic-link members are not allowed" in warnings["symbolic-link"]
    assert "link target: parent-directory traversal" in warnings["symbolic-link"]
    assert "hard-link members are not allowed" in warnings["hard-link"]
    assert "unexpected member type: FIFO" in warnings["device.fifo"]


def test_detects_duplicate_member_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicates.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        add_bytes(archive, "duplicate.txt", b"first")
        add_bytes(archive, "duplicate.txt", b"second")

    inventory = inspect_archive.scan_archive(archive_path)

    assert len(inventory.members) == 2
    assert all(
        "duplicate member path" in member.warnings for member in inventory.members
    )


def test_report_is_deterministic_and_path_free(tmp_path: Path) -> None:
    archive_path = tmp_path / "private-location" / "safe.tar.gz"
    archive_path.parent.mkdir()
    make_safe_archive(archive_path)

    first_inventory = inspect_archive.scan_archive(archive_path)
    second_inventory = inspect_archive.scan_archive(archive_path)
    first_report = inspect_archive.render_report(first_inventory)
    second_report = inspect_archive.render_report(second_inventory)

    assert first_report == second_report
    assert str(tmp_path) not in first_report
    assert "student_export/DATA_DICTIONARY.html" in first_report
    assert "No safety warnings detected." in first_report


def test_cli_writes_report_without_extracting_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "input" / "safe.tar.gz"
    report_path = tmp_path / "output" / "inventory.md"
    archive_path.parent.mkdir()
    make_safe_archive(archive_path)

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            str(archive_path),
            "--report",
            str(report_path),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "Members: 3" in result.stdout
    assert report_path.is_file()
    assert "student_export/customers.parquet" in report_path.read_text(encoding="utf-8")
    assert not (tmp_path / "student_export").exists()
