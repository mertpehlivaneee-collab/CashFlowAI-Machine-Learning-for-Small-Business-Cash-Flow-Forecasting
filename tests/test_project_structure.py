"""Task 1 checks for the intentionally small project scaffold."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_directories_exist() -> None:
    expected_directories = (
        "data/raw",
        "data/interim",
        "data/processed",
        "src/cashflowai",
        "notebooks",
        "tests",
        "reports/figures",
        "reports/data_inspection",
        "docs/project_management",
        "scripts",
    )

    missing = [directory for directory in expected_directories if not (ROOT / directory).is_dir()]

    assert not missing, f"Missing required directories: {missing}"


def test_expected_configuration_files_exist() -> None:
    expected_files = (
        ".gitignore",
        "README.md",
        "requirements.txt",
        "requirements-dev.txt",
        "src/cashflowai/__init__.py",
    )

    missing = [file for file in expected_files if not (ROOT / file).is_file()]

    assert not missing, f"Missing configuration files: {missing}"


def test_gitignore_protects_data_and_local_environment() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for entry in (
        ".venv/",
        "*.tar.gz",
        "*.parquet",
        "data/raw/*",
        "data/interim/*",
        "data/processed/*",
    ):
        assert entry in gitignore


def test_requirements_are_pinned() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    development_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()

    assert requirements == ["pyarrow==23.0.1"]
    assert "pytest==9.0.2" in development_requirements
