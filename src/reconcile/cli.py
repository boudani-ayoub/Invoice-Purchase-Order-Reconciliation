"""Command-line orchestration for the reconciliation pipeline."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from reconcile.errors import CsvValidationError
from reconcile.loaders import load_goods_receipts, load_invoices, load_purchase_orders
from reconcile.reconciliation import reconcile
from reconcile.reporting import (
    render_csv_results,
    render_csv_summary,
    render_json_report,
    render_terminal_report,
)

_CSV_RESULTS_NAME = "reconciliation-results.csv"
_CSV_SUMMARY_NAME = "reconciliation-summary.csv"
_OUTPUT_FORMATS = ("terminal", "json", "csv")
_EXIT_SUCCESS = 0
_EXIT_VALIDATION_ERROR = 3
_EXIT_OUTPUT_ERROR = 4


class _OutputError(Exception):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line workflow and return its process exit code."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.format == "csv" and arguments.output is None:
        parser.error("--output is required when --format csv")
    if arguments.force and arguments.output is None:
        parser.error("--force requires --output")

    try:
        purchase_orders = load_purchase_orders(arguments.purchase_orders)
        receipts = load_goods_receipts(arguments.receipts)
        invoices = load_invoices(arguments.invoices)
        results, summary = reconcile(purchase_orders, receipts, invoices)

        if arguments.format == "csv":
            result_path, summary_path = _preflight_csv_output(
                arguments.output,
                force=arguments.force,
            )
            result_content = render_csv_results(results)
            summary_content = render_csv_summary(summary)
            _write_csv_outputs(
                result_path,
                result_content,
                summary_path,
                summary_content,
                force=arguments.force,
            )
            sys.stdout.write(f"Wrote:\n  {result_path}\n  {summary_path}\n")
            return _EXIT_SUCCESS

        if arguments.output is not None:
            _preflight_file_output(arguments.output, force=arguments.force)

        content = (
            render_json_report(results, summary)
            if arguments.format == "json"
            else render_terminal_report(results, summary)
        )
        if arguments.output is None:
            sys.stdout.write(content)
        else:
            _write_text(arguments.output, content, force=arguments.force)
            sys.stdout.write(f"Wrote report to {arguments.output}\n")
        return _EXIT_SUCCESS
    except CsvValidationError as error:
        sys.stderr.write(f"{error}\n")
        return _EXIT_VALIDATION_ERROR
    except (_OutputError, OSError) as error:
        sys.stderr.write(f"Output error: {error}\n")
        return _EXIT_OUTPUT_ERROR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconcile",
        description="Reconcile supplier invoices against purchase orders and receipts.",
        epilog=(
            "Terminal and JSON reports use stdout unless --output is provided. "
            "CSV requires an output directory and creates two report files."
        ),
    )
    parser.add_argument(
        "--purchase-orders",
        required=True,
        type=Path,
        metavar="PATH",
        help="validated purchase-order CSV input",
    )
    parser.add_argument(
        "--receipts",
        required=True,
        type=Path,
        metavar="PATH",
        help="validated goods-receipt CSV input",
    )
    parser.add_argument(
        "--invoices",
        required=True,
        type=Path,
        metavar="PATH",
        help="validated supplier-invoice CSV input",
    )
    parser.add_argument(
        "--format",
        choices=_OUTPUT_FORMATS,
        default="terminal",
        help="report format (default: terminal)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="terminal/JSON file or CSV output directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace existing report files",
    )
    return parser


def _preflight_file_output(path: Path, *, force: bool) -> None:
    if path.is_dir():
        raise _OutputError(f"expected a file path but received directory: {path}")
    if path.exists() and not force:
        raise _OutputError(f"file already exists: {path}; use --force to replace it")


def _preflight_csv_output(output_dir: Path, *, force: bool) -> tuple[Path, Path]:
    if output_dir.exists() and not output_dir.is_dir():
        raise _OutputError(f"expected a directory path but received file: {output_dir}")

    result_path = output_dir / _CSV_RESULTS_NAME
    summary_path = output_dir / _CSV_SUMMARY_NAME
    directory_targets = tuple(path for path in (result_path, summary_path) if path.is_dir())
    if directory_targets:
        names = ", ".join(str(path) for path in directory_targets)
        raise _OutputError(f"expected report file path but received directory: {names}")
    existing = tuple(path for path in (result_path, summary_path) if path.exists())
    if existing and not force:
        names = ", ".join(str(path) for path in existing)
        raise _OutputError(f"file already exists: {names}; use --force to replace it")
    return result_path, summary_path


def _write_csv_outputs(
    result_path: Path,
    result_content: str,
    summary_path: Path,
    summary_content: str,
    *,
    force: bool,
) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        result_temporary: Path | None = None
        summary_temporary: Path | None = None
        try:
            result_temporary = _write_temporary(result_path, result_content)
            summary_temporary = _write_temporary(summary_path, summary_content)
            result_temporary.replace(result_path)
            summary_temporary.replace(summary_path)
        finally:
            _discard_temporary(result_temporary)
            _discard_temporary(summary_temporary)
        return

    _write_text(result_path, result_content, force=force, create_parent=False)
    _write_text(summary_path, summary_content, force=force, create_parent=False)


def _write_text(
    path: Path,
    content: str,
    *,
    force: bool,
    create_parent: bool = True,
) -> None:
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        temporary_path = _write_temporary(path, content)
        try:
            temporary_path.replace(path)
        finally:
            _discard_temporary(temporary_path)
        return

    try:
        with path.open("x", encoding="utf-8", newline="") as output_file:
            output_file.write(content)
    except FileExistsError as error:
        raise _OutputError(f"file already exists: {path}; use --force to replace it") from error


def _write_temporary(path: Path, content: str) -> Path:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except BaseException:
        _discard_temporary(temporary_path)
        raise


def _discard_temporary(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
