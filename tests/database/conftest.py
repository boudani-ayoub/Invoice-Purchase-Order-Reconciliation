"""Database cases own disposable state and keep tenant fixtures independent."""

import os
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")
from sqlalchemy.orm import Session

from reconcile.persistence import models as db
from scripts.postgres_testing import provision_database


@pytest.fixture(scope="session")
def database():
    configured = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not configured:
        pytest.skip("Set TEST_DATABASE_ADMIN_URL to enable real PostgreSQL integration tests")
    with provision_database(configured) as instance:
        yield instance


@dataclass
class TenantData:
    organization: UUID
    supplier: UUID
    item: UUID
    source: UUID
    invoice: UUID
    po: UUID
    po_line: UUID
    receipt: UUID


@pytest.fixture
def tenants(database):
    def seed():
        with Session(database.admin) as session, session.begin():
            organization = db.Organization(name="Test organization", slug=f"test-{uuid4().hex}")
            session.add(organization)
            session.flush()
            org = organization.id
            supplier = db.Supplier(organization_id=org, supplier_code="SUP", name="Supplier")
            item = db.Item(organization_id=org, item_code="ITEM", description="Parts")
            sources = [
                db.SourceFile(
                    organization_id=org,
                    source_type=kind,
                    original_filename=f"{kind.value}.csv",
                    size_bytes=123,
                    sha256="a" * 64,
                )
                for kind in db.SourceType
            ]
            session.add_all([supplier, item, *sources])
            session.flush()
            source_ids = {source.source_type: source.id for source in sources}
            po = db.PurchaseOrder(
                organization_id=org,
                source_file_id=source_ids[db.SourceType.PURCHASE_ORDERS],
                po_number="PO",
                source_supplier_code="SUP",
                order_date=date(2026, 1, 1),
                currency="EUR",
            )
            invoice = db.Invoice(
                organization_id=org,
                source_file_id=source_ids[db.SourceType.INVOICES],
                invoice_number="INV",
                source_supplier_code="SUP",
                invoice_date=date(2026, 1, 1),
                currency="EUR",
            )
            receipt = db.GoodsReceipt(
                organization_id=org,
                source_file_id=source_ids[db.SourceType.RECEIPTS],
                receipt_number="REC",
            )
            session.add_all([po, invoice, receipt])
            session.flush()
            line = db.PurchaseOrderLine(
                organization_id=org,
                purchase_order_id=po.id,
                line_number=1,
                source_row_number=2,
                source_item_code="ITEM",
                description="Parts",
                ordered_quantity=100,
                unit_price=10,
            )
            session.add(line)
            session.flush()
            return TenantData(
                org,
                supplier.id,
                item.id,
                source_ids[db.SourceType.INVOICES],
                invoice.id,
                po.id,
                line.id,
                receipt.id,
            )

    return seed(), seed()
