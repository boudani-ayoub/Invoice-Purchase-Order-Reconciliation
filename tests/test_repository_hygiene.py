from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_committed_project_content_has_no_local_absolute_paths() -> None:
    project_files = [
        REPOSITORY_ROOT / "README.md",
        REPOSITORY_ROOT / "SECURITY.md",
        REPOSITORY_ROOT / "pyproject.toml",
        *sorted((REPOSITORY_ROOT / "docs").glob("*.md")),
        *sorted((REPOSITORY_ROOT / "src").rglob("*.py")),
    ]
    local_path_markers = ("C:/Users/", "C:\\Users\\", "/home/")

    offenders = [
        path.relative_to(REPOSITORY_ROOT)
        for path in project_files
        if path.exists()
        and any(marker in path.read_text(encoding="utf-8") for marker in local_path_markers)
    ]

    assert offenders == []
