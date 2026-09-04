"""Structured errors raised while validating source CSV files."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CsvValidationIssue:
    source: Path
    row_number: int | None
    column: str
    value: str
    reason: str

    def __str__(self) -> str:
        location = str(self.source)
        if self.row_number is not None:
            location = f"{location}:{self.row_number}"
        return f"{location}\ncolumn: {self.column}\nvalue: {self.value!r}\nreason: {self.reason}"


class CsvValidationError(ValueError):
    """One or more structural or scalar validation issues in a CSV source."""

    def __init__(self, issues: Iterable[CsvValidationIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("CsvValidationError requires at least one issue")
        super().__init__(str(self))

    def __str__(self) -> str:
        label = "issue" if len(self.issues) == 1 else "issues"
        details = "\n\n".join(str(issue) for issue in self.issues)
        return f"CSV validation failed with {len(self.issues)} {label}:\n\n{details}"
