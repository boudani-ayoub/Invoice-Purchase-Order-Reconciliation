"""Safe received-file metadata and physical CSV row positions, never retained bytes."""

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from reconcile.persistence.run_policy import FILENAME_LIMIT


@dataclass(frozen=True)
class UploadedSource:
    filename: str
    size_bytes: int
    sha256: str


def safe_filename(value: str | None) -> str:
    basename = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
    safe = "".join(char for char in basename if not unicodedata.category(char).startswith("C"))
    safe = safe.strip(" .")[:FILENAME_LIMIT]
    return safe or "source.csv"


def source_row_numbers(path: Path) -> tuple[int, ...]:
    # Loaders own validation; this pass preserves their physical end-line convention.
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        next(reader)
        return tuple(reader.line_num for _ in reader)
