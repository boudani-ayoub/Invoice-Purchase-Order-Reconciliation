import tomllib
from importlib.metadata import version
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
DISTRIBUTION_NAME = "invoice-purchase-order-reconciliation"


def test_installed_distribution_matches_project_version() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert version(DISTRIBUTION_NAME) == project["project"]["version"]
