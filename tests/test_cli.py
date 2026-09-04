import csv
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

import reconcile.cli as cli_module
from reconcile import (
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
    reconcile,
    render_csv_results,
    render_csv_summary,
    render_json_report,
    render_terminal_report,
)
from reconcile.cli import main

SAMPLE_DIR = Path(__file__).parents[1] / "examples" / "sample_data"


def sample_args(*extra: str) -> list[str]:
    return [
        "--purchase-orders",
        str(SAMPLE_DIR / "purchase_orders.csv"),
        "--receipts",
        str(SAMPLE_DIR / "goods_receipts.csv"),
        "--invoices",
        str(SAMPLE_DIR / "invoices.csv"),
        *extra,
    ]


def sample_report_data():
    purchase_orders = load_purchase_orders(SAMPLE_DIR / "purchase_orders.csv")
    receipts = load_goods_receipts(SAMPLE_DIR / "goods_receipts.csv")
    invoices = load_invoices(SAMPLE_DIR / "invoices.csv")
    return reconcile(purchase_orders, receipts, invoices)


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    output = capsys.readouterr()
    assert exit_info.value.code == 0
    assert "Reconcile supplier invoices" in output.out
    assert "--purchase-orders" in output.out
    assert "--receipts" in output.out
    assert "--invoices" in output.out
    assert "--format {terminal,json,csv}" in output.out
    assert "--output" in output.out
    assert "--force" in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--purchase-orders", "purchase_orders.csv"],
        [
            "--purchase-orders",
            "purchase_orders.csv",
            "--receipts",
            "receipts.csv",
            "--invoices",
            "invoices.csv",
            "--format",
            "xml",
        ],
        ["--unknown-option"],
    ],
    ids=("missing-all", "missing-invoices", "invalid-format", "unknown-option"),
)
def test_usage_errors_exit_with_code_two(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    output = capsys.readouterr()
    assert exit_info.value.code == 2
    assert output.out == ""
    assert "usage: reconcile" in output.err


def test_csv_requires_output_directory(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(sample_args("--format", "csv"))

    output = capsys.readouterr()
    assert exit_info.value.code == 2
    assert output.out == ""
    assert "--output is required when --format csv" in output.err


def test_force_requires_output(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(sample_args("--force"))

    output = capsys.readouterr()
    assert exit_info.value.code == 2
    assert output.out == ""
    assert "--force requires --output" in output.err


def test_default_terminal_report_is_written_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(sample_args())

    output = capsys.readouterr()
    results, summary = sample_report_data()
    assert exit_code == 0
    assert output.out == render_terminal_report(results, summary)
    assert "INVOICE / PURCHASE ORDER RECONCILIATION" in output.out
    assert "Invoices processed: 15" in output.out
    assert "Invoice lines processed: 17" in output.out
    assert "Matched: 6" in output.out
    assert "Review required: 11" in output.out
    assert "EUR: 2450.00" in output.out
    assert "MAD: 10199.00" in output.out
    assert "USD: 75.00" in output.out
    assert output.err == ""


def test_json_report_is_written_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(sample_args("--format", "json"))

    output = capsys.readouterr()
    results, summary = sample_report_data()
    report = json.loads(output.out)
    assert exit_code == 0
    assert output.out == render_json_report(results, summary)
    assert report["summary"]["invoices_processed"] == 15
    assert report["summary"]["invoice_lines_processed"] == 17
    assert report["summary"]["matched_lines"] == 6
    assert report["summary"]["review_required_lines"] == 11
    assert report["summary"]["issue_counts"] == {
        "UNKNOWN_PO": 1,
        "UNKNOWN_ITEM": 1,
        "DUPLICATE_INVOICE": 2,
        "SUPPLIER_MISMATCH": 1,
        "CURRENCY_MISMATCH": 1,
        "MISSING_RECEIPT": 1,
        "QUANTITY_EXCEEDS_PO": 2,
        "QUANTITY_EXCEEDS_RECEIPT": 2,
        "PRICE_MISMATCH": 1,
    }
    assert report["summary"]["disputed_amounts"] == {
        "EUR": "2450.00",
        "MAD": "10199.00",
        "USD": "75.00",
    }
    assert len(report["results"]) == 17
    assert output.err == ""


@pytest.mark.parametrize(
    ("output_format", "renderer"),
    [("terminal", render_terminal_report), ("json", render_json_report)],
)
def test_single_report_file_is_exact_and_parent_directories_are_created(
    output_format,
    renderer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "nested" / f"report.{output_format}"
    results, summary = sample_report_data()

    exit_code = main(sample_args("--format", output_format, "--output", str(output_path)))

    output = capsys.readouterr()
    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == renderer(results, summary)
    assert output_path.read_bytes() == renderer(results, summary).encode("utf-8")
    assert output.out == f"Wrote report to {output_path}\n"
    assert output.err == ""


def test_csv_writes_two_parseable_reports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "nested" / "reports"

    exit_code = main(sample_args("--format", "csv", "--output", str(output_dir)))

    output = capsys.readouterr()
    created = sorted(path.name for path in output_dir.iterdir())
    result_path = output_dir / "reconciliation-results.csv"
    summary_path = output_dir / "reconciliation-summary.csv"
    result_rows = list(csv.DictReader(StringIO(result_path.read_text(encoding="utf-8"))))
    summary_rows = list(csv.reader(StringIO(summary_path.read_text(encoding="utf-8"))))
    assert exit_code == 0
    assert created == ["reconciliation-results.csv", "reconciliation-summary.csv"]
    assert len(result_rows) == 17
    assert ["metric", "invoices_processed", "15"] in summary_rows
    assert ["metric", "invoice_lines_processed", "17"] in summary_rows
    assert ["metric", "matched_lines", "6"] in summary_rows
    assert ["metric", "review_required_lines", "11"] in summary_rows
    assert ["issue", "DUPLICATE_INVOICE", "2"] in summary_rows
    assert ["disputed_amount", "EUR", "2450.00"] in summary_rows
    assert ["disputed_amount", "MAD", "10199.00"] in summary_rows
    assert ["disputed_amount", "USD", "75.00"] in summary_rows
    assert output.out == f"Wrote:\n  {result_path}\n  {summary_path}\n"
    assert output.err == ""


@pytest.mark.parametrize(
    ("output_format", "renderer"),
    [("terminal", render_terminal_report), ("json", render_json_report)],
)
def test_single_report_refuses_overwrite_then_force_replaces_it(
    output_format,
    renderer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "report.txt"
    output_path.write_text("original", encoding="utf-8")

    refused = main(sample_args("--format", output_format, "--output", str(output_path)))
    refusal_output = capsys.readouterr()

    assert refused == 4
    assert output_path.read_text(encoding="utf-8") == "original"
    assert refusal_output.out == ""
    assert "already exists" in refusal_output.err
    assert "--force" in refusal_output.err

    replaced = main(
        sample_args(
            "--format",
            output_format,
            "--output",
            str(output_path),
            "--force",
        )
    )
    replacement_output = capsys.readouterr()
    results, summary = sample_report_data()

    assert replaced == 0
    assert output_path.read_text(encoding="utf-8") == renderer(results, summary)
    assert replacement_output.out == f"Wrote report to {output_path}\n"
    assert replacement_output.err == ""


def test_csv_preflight_prevents_partial_overwrite_then_force_writes_both(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    result_path = output_dir / "reconciliation-results.csv"
    summary_path = output_dir / "reconciliation-summary.csv"
    summary_path.write_text("original", encoding="utf-8")

    refused = main(sample_args("--format", "csv", "--output", str(output_dir)))
    refusal_output = capsys.readouterr()

    assert refused == 4
    assert not result_path.exists()
    assert summary_path.read_text(encoding="utf-8") == "original"
    assert refusal_output.out == ""
    assert "reconciliation-summary.csv" in refusal_output.err
    assert "--force" in refusal_output.err

    replaced = main(sample_args("--format", "csv", "--output", str(output_dir), "--force"))
    replacement_output = capsys.readouterr()
    results, summary = sample_report_data()

    assert replaced == 0
    assert result_path.read_text(encoding="utf-8") == render_csv_results(results)
    assert summary_path.read_text(encoding="utf-8") == render_csv_summary(summary)
    assert replacement_output.err == ""


def test_validation_error_uses_stderr_and_creates_no_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid_po = tmp_path / "invalid-purchase-orders.csv"
    invalid_po.write_text(
        "po_number,line_number,supplier_id,order_date,currency,item_code,description,"
        "ordered_quantity,unit_price\n"
        "PO-100,1,SUP-ONE,2026-01-01,MAD,ITEM-A,Item,-3,10\n",
        encoding="utf-8",
        newline="",
    )
    output_path = tmp_path / "report.json"
    arguments = sample_args("--format", "json", "--output", str(output_path))
    arguments[1] = str(invalid_po)

    exit_code = main(arguments)

    output = capsys.readouterr()
    assert exit_code == 3
    assert output.out == ""
    assert "CSV validation failed with 1 issue" in output.err
    assert "invalid-purchase-orders.csv:2" in output.err
    assert "column: ordered_quantity" in output.err
    assert "value: '-3'" in output.err
    assert "must be a finite decimal greater than zero" in output.err
    assert "Traceback" not in output.err
    assert not output_path.exists()


def test_missing_input_uses_validation_exit_and_creates_no_csv_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "reports"
    arguments = sample_args("--format", "csv", "--output", str(output_dir))
    arguments[1] = str(tmp_path / "missing.csv")

    exit_code = main(arguments)

    output = capsys.readouterr()
    assert exit_code == 3
    assert output.out == ""
    assert "unable to read file" in output.err
    assert "missing.csv" in output.err
    assert not output_dir.exists()


@pytest.mark.parametrize("output_format", ["terminal", "json"])
def test_file_output_rejects_directory_target(
    output_format: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(sample_args("--format", output_format, "--output", str(tmp_path), "--force"))

    output = capsys.readouterr()
    assert exit_code == 4
    assert output.out == ""
    assert "expected a file path" in output.err


def test_csv_output_rejects_file_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "report-target"
    output_path.write_text("existing", encoding="utf-8")

    exit_code = main(sample_args("--format", "csv", "--output", str(output_path), "--force"))

    output = capsys.readouterr()
    assert exit_code == 4
    assert output_path.read_text(encoding="utf-8") == "existing"
    assert output.out == ""
    assert "expected a directory path" in output.err


def test_csv_force_rejects_report_directory_before_writing_other_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    summary_path = output_dir / "reconciliation-summary.csv"
    summary_path.mkdir()

    exit_code = main(sample_args("--format", "csv", "--output", str(output_dir), "--force"))

    output = capsys.readouterr()
    assert exit_code == 4
    assert not (output_dir / "reconciliation-results.csv").exists()
    assert summary_path.is_dir()
    assert output.out == ""
    assert "expected report file path" in output.err


def test_force_preserves_existing_report_when_temporary_write_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "report.json"
    output_path.write_text("original", encoding="utf-8")

    def fail_write(path: Path, content: str) -> Path:
        raise OSError("simulated temporary write failure")

    monkeypatch.setattr(cli_module, "_write_temporary", fail_write)

    exit_code = main(sample_args("--format", "json", "--output", str(output_path), "--force"))

    output = capsys.readouterr()
    assert exit_code == 4
    assert output_path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []
    assert output.out == ""
    assert "simulated temporary write failure" in output.err


def test_csv_force_preserves_both_reports_when_second_temporary_write_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    result_path = output_dir / "reconciliation-results.csv"
    summary_path = output_dir / "reconciliation-summary.csv"
    result_path.write_text("original results", encoding="utf-8")
    summary_path.write_text("original summary", encoding="utf-8")
    original_write = cli_module._write_temporary
    call_count = 0

    def fail_second_write(path: Path, content: str) -> Path:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("simulated second temporary write failure")
        return original_write(path, content)

    monkeypatch.setattr(cli_module, "_write_temporary", fail_second_write)

    exit_code = main(sample_args("--format", "csv", "--output", str(output_dir), "--force"))

    output = capsys.readouterr()
    assert exit_code == 4
    assert result_path.read_text(encoding="utf-8") == "original results"
    assert summary_path.read_text(encoding="utf-8") == "original summary"
    assert list(output_dir.glob("*.tmp")) == []
    assert output.out == ""
    assert "simulated second temporary write failure" in output.err


def test_module_entry_point_help_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "reconcile", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "usage: reconcile" in completed.stdout
    assert "--purchase-orders" in completed.stdout
    assert completed.stderr == ""
