import csv
import io
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from itertools import permutations

import pytest
from fastapi.testclient import TestClient
from web_support import create_analysis_test_app as create_app

from reconcile.analysis import analyze_invoice_po, analyze_invoice_receipt, analyze_po_receipt
from reconcile.analysis.models import REQUIRED_SOURCES, AnalysisMode
from reconcile.models import GoodsReceiptLine, InvoiceLine, PurchaseOrderLine
from reconcile.web.app import ANALYSES_PATH

DAY = date(2026, 1, 1)
PO = PurchaseOrderLine("PO-1", 1, "SUP-1", DAY, "EUR", "ITEM-1", "Parts", Decimal(100), Decimal(10))
RECEIPT = GoodsReceiptLine("REC-1", 1, "PO-1", 1, DAY, "ITEM-1", Decimal(100))
INVOICE = InvoiceLine(
    "INV-A", 1, "SUP-1", DAY, "PO-1", 1, "EUR", "ITEM-1", Decimal(100), Decimal(10)
)


def uploads(*, orders=(PO,), receipts=(RECEIPT,), invoices=(INVOICE,)):
    files = {}
    for field, rows in (
        ("purchase_orders", orders),
        ("receipts", receipts),
        ("invoices", invoices),
    ):
        if not rows:
            continue
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=asdict(rows[0]))
        writer.writeheader()
        writer.writerows(
            {
                key: format(value, "f") if isinstance(value, Decimal) else value
                for key, value in asdict(row).items()
            }
            for row in rows
        )
        files[field] = (
            "../../untrusted.exe",
            output.getvalue().encode(),
            "application/octet-stream",
        )
    return files


def post(mode, **sources):
    files = uploads(**sources)
    with TestClient(create_app()) as client:
        return client.post(
            f"{ANALYSES_PATH}/{mode}", files={key: files[key] for key in REQUIRED_SOURCES[mode]}
        )


@pytest.mark.parametrize("mode", AnalysisMode)
def test_exact_match_and_mode_specific_shape(mode):
    response = post(mode)
    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == mode
    row = report["results"][0]
    if mode == AnalysisMode.PO_RECEIPT:
        assert row["status"] == "FULLY_RECEIVED"
        assert "invoice_number" not in row
        assert report["orphan_receipts"] == []
    else:
        assert row["status"] == "MATCHED"
        assert row["supported_quantity"] == "100"
    if mode == AnalysisMode.INVOICE_PO:
        assert "received_quantity" not in row
    if mode == AnalysisMode.INVOICE_RECEIPT:
        assert "po_unit_price" not in row
        assert "ordered_quantity" not in row
        assert "potential_disputed_amount" not in row


@pytest.mark.parametrize(
    ("changes", "issue", "exposure"),
    [
        ({"unit_price": Decimal("12")}, "PRICE_MISMATCH", "200.00"),
        ({"unit_price": Decimal("9")}, "PRICE_MISMATCH", "0.00"),
        ({"supplier_id": "DIFFERENT"}, "SUPPLIER_MISMATCH", "1000.00"),
        ({"currency": "MAD"}, "CURRENCY_MISMATCH", "1000.00"),
        ({"invoiced_quantity": Decimal(120)}, "QUANTITY_EXCEEDS_PO", "200.00"),
        ({"po_number": "ABSENT"}, "UNKNOWN_PO", "1000.00"),
        ({"po_line_number": 2}, "UNKNOWN_ITEM", "1000.00"),
        ({"item_code": "OTHER"}, "UNKNOWN_ITEM", "1000.00"),
    ],
)
def test_invoice_po_controls_without_receipt_rules(changes, issue, exposure):
    report = post(AnalysisMode.INVOICE_PO, invoices=(replace(INVOICE, **changes),)).json()
    row = report["results"][0]
    assert row["issues"] == [issue]
    assert row["potential_disputed_amount"] == exposure
    assert "MISSING_RECEIPT" not in report["summary"]["issue_counts"]
    assert "QUANTITY_EXCEEDS_RECEIPT" not in report["summary"]["issue_counts"]


@pytest.mark.parametrize("mode", [AnalysisMode.INVOICE_PO, AnalysisMode.INVOICE_RECEIPT])
def test_cumulative_invoice_capacity(mode):
    invoices = (
        replace(INVOICE, invoiced_quantity=Decimal(70)),
        replace(INVOICE, invoice_number="INV-B", invoiced_quantity=Decimal(50)),
    )
    report = post(mode, invoices=invoices).json()
    assert [row["supported_quantity"] for row in report["results"]] == ["70", "30"]
    assert report["results"][1]["previously_invoiced_quantity"] == "70"
    assert report["summary"]["review_required_lines"] == 1
    totals = "disputed_amounts" if mode == AnalysisMode.INVOICE_PO else "unsupported_amounts"
    assert report["summary"][totals] == {"EUR": "200.00"}


@pytest.mark.parametrize("mode", [AnalysisMode.INVOICE_PO, AnalysisMode.INVOICE_RECEIPT])
def test_duplicate_group_consumes_maximum_once_and_summary_does_not_double_count(mode):
    invoices = (
        replace(INVOICE, invoiced_quantity=Decimal(60)),
        replace(INVOICE, invoiced_quantity=Decimal(70)),
        replace(INVOICE, invoice_number="INV-B", invoiced_quantity=Decimal(40)),
    )
    report = post(mode, invoices=invoices).json()
    assert all("DUPLICATE_INVOICE" in row["issues"] for row in report["results"][:2])
    assert report["results"][2]["previously_invoiced_quantity"] == "70"
    assert report["results"][2]["supported_quantity"] == "30"
    totals = "disputed_amounts" if mode == AnalysisMode.INVOICE_PO else "unsupported_amounts"
    assert report["summary"][totals] == {"EUR": "800.00"}


@pytest.mark.parametrize("mode", [AnalysisMode.INVOICE_PO, AnalysisMode.INVOICE_RECEIPT])
def test_ambiguous_duplicates_receive_no_allocation_and_consume_nothing(mode):
    invoices = (
        INVOICE,
        replace(INVOICE, po_number="PO-2"),
        replace(INVOICE, invoice_number="INV-B"),
    )
    orders = (PO, replace(PO, po_number="PO-2"))
    receipts = (RECEIPT, replace(RECEIPT, receipt_id="REC-2", po_number="PO-2"))
    report = post(mode, invoices=invoices, orders=orders, receipts=receipts).json()
    assert [row["supported_quantity"] for row in report["results"]] == ["0", "0", "100"]
    assert report["results"][2]["status"] == "MATCHED"


@pytest.mark.parametrize(
    ("receipt", "issues", "exposure"),
    [
        (replace(RECEIPT, po_number="OTHER"), ["MISSING_RECEIPT"], "1000.00"),
        (
            replace(RECEIPT, item_code="OTHER"),
            ["MISSING_RECEIPT", "RECEIPT_ITEM_MISMATCH"],
            "1000.00",
        ),
        (replace(RECEIPT, received_quantity=Decimal(70)), ["QUANTITY_EXCEEDS_RECEIPT"], "300.00"),
    ],
)
def test_receipt_coverage_findings(receipt, issues, exposure):
    row = post(AnalysisMode.INVOICE_RECEIPT, receipts=(receipt,)).json()["results"][0]
    assert row["issues"] == issues
    assert row["potential_unsupported_amount"] == exposure


def test_receipt_coverage_has_no_commercial_checks():
    invoice = replace(INVOICE, supplier_id="ANY", currency="MAD", unit_price=Decimal("999.99"))
    row = post(AnalysisMode.INVOICE_RECEIPT, invoices=(invoice,)).json()["results"][0]
    assert row["issues"] == []
    assert row["potential_unsupported_amount"] == "0.00"


@pytest.mark.parametrize("mode", [AnalysisMode.INVOICE_RECEIPT, AnalysisMode.PO_RECEIPT])
def test_multiple_receipts_aggregate(mode):
    receipts = (
        replace(RECEIPT, received_quantity=Decimal(70)),
        replace(RECEIPT, receipt_id="REC-2", received_quantity=Decimal(30)),
    )
    row = post(mode, receipts=receipts).json()["results"][0]
    assert row["received_quantity"] == "100"


@pytest.mark.parametrize(
    ("received", "status", "outstanding", "excess"),
    [
        (100, "FULLY_RECEIVED", "0", "0"),
        (70, "PARTIALLY_RECEIVED", "30", "0"),
        (120, "OVER_RECEIVED", "0", "20"),
    ],
)
def test_fulfillment_states(received, status, outstanding, excess):
    row = post(
        AnalysisMode.PO_RECEIPT, receipts=(replace(RECEIPT, received_quantity=Decimal(received)),)
    ).json()["results"][0]
    assert row["status"] == status
    assert row["outstanding_quantity"] == outstanding
    assert row["over_received_quantity"] == excess
    assert "potential_disputed_amount" not in row


@pytest.mark.parametrize(
    ("changes", "issue"),
    [
        ({"po_number": "ABSENT"}, "UNKNOWN_PO"),
        ({"po_line_number": 2}, "UNKNOWN_ITEM"),
        ({"item_code": "OTHER"}, "RECEIPT_ITEM_MISMATCH"),
    ],
)
def test_orphan_receipts_are_visible_and_do_not_support_order(changes, issue):
    report = post(AnalysisMode.PO_RECEIPT, receipts=(replace(RECEIPT, **changes),)).json()
    assert report["orphan_receipts"][0]["issue"] == issue
    assert report["results"][0]["status"] == "NOT_RECEIVED"
    assert report["summary"]["outstanding_values"] == {"EUR": "1000.00"}
    assert report["summary"]["orphan_receipt_lines"] == 1


def test_new_three_way_matches_legacy_json_contract():
    from test_web_api import upload_files

    with TestClient(create_app()) as client:
        legacy = client.post("/api/v1/reconcile", files=upload_files())
        report = client.post(f"{ANALYSES_PATH}/{AnalysisMode.THREE_WAY}", files=upload_files())
    payload = report.json()
    assert payload.pop("mode") == "three-way"
    assert payload == legacy.json()


def test_three_way_parity_includes_small_fixed_point_decimals():
    files = uploads(invoices=(replace(INVOICE, unit_price=Decimal("0.0000001")),))
    with TestClient(create_app()) as client:
        legacy = client.post("/api/v1/reconcile", files=files).json()
        modern = client.post(f"{ANALYSES_PATH}/three-way", files=files).json()
    modern.pop("mode")
    assert modern == legacy
    assert modern["results"][0]["invoice_unit_price"] == "0.0000001"


@pytest.mark.parametrize("mode", AnalysisMode)
def test_explicit_openapi_requirements_and_missing_file_errors(mode):
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
        operation = schema["paths"][f"{ANALYSES_PATH}/{mode}"]["post"]
        ref = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        body = schema["components"]["schemas"][ref.split("/")[-1]]
        assert set(body["required"]) == set(REQUIRED_SOURCES[mode])
        assert set(body["properties"]) == set(REQUIRED_SOURCES[mode])
        for missing in REQUIRED_SOURCES[mode]:
            files = {key: val for key, val in uploads().items() if key != missing}
            assert client.post(f"{ANALYSES_PATH}/{mode}", files=files).status_code == 422


@pytest.mark.parametrize("mode", AnalysisMode)
@pytest.mark.parametrize("failure", ["size", "utf8", "unexpected"])
def test_new_upload_security_and_cleanup(mode, failure, monkeypatch, tmp_path):
    from contextlib import contextmanager

    import reconcile.web.app as web_app

    directory = tmp_path / "request"

    @contextmanager
    def request_directory():
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(dir=tmp_path) as value:
            nonlocal directory
            from pathlib import Path

            directory = Path(value)
            yield value

    monkeypatch.setattr(web_app, "_request_directory", request_directory)
    files = {key: val for key, val in uploads().items() if key in REQUIRED_SOURCES[mode]}
    field = REQUIRED_SOURCES[mode][0]
    if failure == "size":
        files[field] = ("bad.csv", b"x" * 1000, "text/csv")
    elif failure == "utf8":
        files[field] = ("bad.csv", b"\xff\xfe", "text/csv")
    else:

        def fail(*args):
            raise RuntimeError("private-detail")

        monkeypatch.setattr(web_app, "render_analysis", fail)
    with TestClient(
        create_app(max_upload_bytes=500 if failure == "size" else 10000),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(f"{ANALYSES_PATH}/{mode}", files=files)
    assert response.status_code == {"size": 413, "utf8": 422, "unexpected": 500}[failure]
    assert "private-detail" not in response.text
    assert str(tmp_path) not in response.text
    assert not directory.exists()


def test_source_order_does_not_change_pairwise_results():
    invoices = (
        replace(INVOICE, invoiced_quantity=Decimal(60)),
        replace(INVOICE, invoiced_quantity=Decimal(70)),
        replace(INVOICE, invoice_number="INV-B", invoiced_quantity=Decimal(40)),
    )
    for reordered in permutations(invoices):
        assert analyze_invoice_po((PO,), reordered) == analyze_invoice_po((PO,), invoices)
        assert analyze_invoice_receipt((RECEIPT,), reordered) == analyze_invoice_receipt(
            (RECEIPT,), invoices
        )
    receipts = (
        replace(RECEIPT, received_quantity=Decimal(70)),
        replace(RECEIPT, receipt_id="REC-2", received_quantity=Decimal(30)),
    )
    assert analyze_po_receipt((PO,), receipts) == analyze_po_receipt((PO,), reversed(receipts))


def test_fractional_quantity_and_price_remain_decimal():
    invoice = replace(INVOICE, invoiced_quantity=Decimal("0.3"), unit_price=Decimal("0.1"))
    receipt = replace(RECEIPT, received_quantity=Decimal("0.1"))
    rows, summary = analyze_invoice_receipt((receipt,), (invoice,))
    assert rows[0].potential_unsupported_amount == Decimal("0.02")
    assert summary.unsupported_amounts[0].amount == Decimal("0.02")
