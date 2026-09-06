"""Tests own a new database and two roles; existing databases are never reset."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from reconcile.persistence import models as db
from reconcile.persistence.session import RUNTIME_GROUP, database_url


@dataclass
class Database:
    admin: Engine
    runtime: Engine
    migration_url: str


@pytest.fixture(scope="session")
def database():
    configured = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not configured:
        pytest.skip("Set TEST_DATABASE_ADMIN_URL to enable real PostgreSQL integration tests")
    admin_url = database_url(configured)
    suffix = uuid4().hex[:16]
    db_name, owner, runtime = (
        f"reconcile_test_{suffix}{tail}" for tail in ("", "_owner", "_runtime")
    )
    password = uuid4().hex
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as connection:
        cursor = connection.connection.driver_connection.cursor()
        if not cursor.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_GROUP,)
        ).fetchone():
            cursor.execute(
                sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
                    sql.Identifier(RUNTIME_GROUP)
                )
            )
        for role in (owner, runtime):
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(RUNTIME_GROUP), sql.Identifier(role)
                )
            )
        cursor.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(db_name), sql.Identifier(owner)
            )
        )
    owner_url = admin_url.set(database=db_name, username=owner, password=password)
    runtime_url = admin_url.set(database=db_name, username=runtime, password=password)
    data_admin = create_engine(admin_url.set(database=db_name), hide_parameters=True)
    runtime_engine = create_engine(runtime_url, pool_size=1, max_overflow=0, hide_parameters=True)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", owner_url.render_as_string(hide_password=False))
            command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
        yield Database(data_admin, runtime_engine, owner_url.render_as_string(hide_password=False))
    finally:
        runtime_engine.dispose()
        data_admin.dispose()
        with admin.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db_name)))
            for role in (runtime, owner):
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        admin.dispose()


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
