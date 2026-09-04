from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from reconcile.models import InvoiceLine, IssueCode, ReconciliationStatus


def test_invoice_line_preserves_decimal_values() -> None:
    invoice = InvoiceLine(
        invoice_number="INV-001",
        line_number=1,
        supplier_id="SUP-ALPHA",
        invoice_date=date(2026, 1, 10),
        po_number="PO-001",
        po_line_number=1,
        currency="MAD",
        item_code="LAPTOP-STAND",
        invoiced_quantity=Decimal("10"),
        unit_price=Decimal("250.00"),
    )

    assert invoice.invoiced_quantity == Decimal("10")
    assert invoice.unit_price == Decimal("250.00")


def test_domain_models_are_immutable() -> None:
    invoice = InvoiceLine(
        invoice_number="INV-001",
        line_number=1,
        supplier_id="SUP-ALPHA",
        invoice_date=date(2026, 1, 10),
        po_number="PO-001",
        po_line_number=1,
        currency="MAD",
        item_code="LAPTOP-STAND",
        invoiced_quantity=Decimal("10"),
        unit_price=Decimal("250.00"),
    )

    with pytest.raises(FrozenInstanceError):
        invoice.currency = "USD"  # type: ignore[misc]


def test_result_codes_are_stable_strings() -> None:
    assert ReconciliationStatus.REVIEW_REQUIRED == "REVIEW_REQUIRED"
    assert IssueCode.QUANTITY_EXCEEDS_PO == "QUANTITY_EXCEEDS_PO"
