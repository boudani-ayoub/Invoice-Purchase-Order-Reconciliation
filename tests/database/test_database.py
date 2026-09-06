from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from reconcile.persistence import models as db
from reconcile.persistence.base import Base
from reconcile.persistence.session import TENANT_SETTING, database_url, tenant_session

pytestmark = pytest.mark.database


def invoice_line(tenant, **changes):
    values = dict(
        organization_id=tenant.organization,
        invoice_id=tenant.invoice,
        line_number=1,
        source_row_number=2,
        source_po_number="UNKNOWN",
        source_po_line_number=99,
        source_item_code="WRONG-ITEM",
        invoiced_quantity=120,
        unit_price=12,
    )
    return db.InvoiceLine(**(values | changes))


def test_migration_upgrade_and_metadata_parity(database, monkeypatch):
    assert set(inspect(database.admin).get_table_names()) == set(Base.metadata.tables) | {
        "alembic_version"
    }
    monkeypatch.setenv("DATABASE_URL", database.migration_url)
    command.check(Config(str(Path(__file__).parents[2] / "alembic.ini")))


def test_runtime_is_not_owner_superuser_or_bypassrls(database):
    with database.runtime.connect() as connection:
        role = connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert tuple(role) == (False, False)
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
                    "AND tableowner = current_user"
                )
            )
            == 0
        )


def test_every_table_has_forced_rls(database):
    with database.admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "JOIN pg_namespace ON pg_namespace.oid = relnamespace "
                "WHERE nspname = 'public' AND relkind = 'r' AND relname <> 'alembic_version'"
            )
        )
        assert {name for name, enabled, forced in rows if enabled and forced} == set(
            Base.metadata.tables
        )


def test_rls_a_cannot_read_b(database, tenants):
    a, b = tenants
    with tenant_session(database.runtime, a.organization) as session:
        assert session.get(db.Supplier, a.supplier) is not None
        assert session.get(db.Supplier, b.supplier) is None
        assert {row.id for row in session.scalars(select(db.Organization))} == {a.organization}
        assert {row.organization_id for row in session.scalars(select(db.Invoice))} == {
            a.organization
        }


def test_rls_a_cannot_update_b(database, tenants):
    a, b = tenants
    with tenant_session(database.runtime, a.organization) as session:
        assert (
            session.execute(
                update(db.Supplier).where(db.Supplier.id == b.supplier).values(name="Changed")
            ).rowcount
            == 0
        )
        assert (
            session.execute(
                update(db.Supplier).where(db.Supplier.id == a.supplier).values(name="Own change")
            ).rowcount
            == 1
        )
    with Session(database.admin) as session:
        assert session.get(db.Supplier, b.supplier).name == "Supplier"


def test_rls_a_cannot_insert_b_owned_row(database, tenants):
    a, b = tenants
    with pytest.raises(DBAPIError):
        with tenant_session(database.runtime, a.organization) as session:
            session.add(
                db.Item(organization_id=b.organization, item_code="CROSS", description="Denied")
            )


def test_rls_prevents_reassigning_ownership(database, tenants):
    a, b = tenants
    with pytest.raises(DBAPIError):
        with tenant_session(database.runtime, a.organization) as session:
            session.execute(
                update(db.Supplier)
                .where(db.Supplier.id == a.supplier)
                .values(organization_id=b.organization)
            )


def test_missing_tenant_context_fails_closed(database, tenants):
    a, _ = tenants
    with Session(database.runtime) as session:
        assert list(session.scalars(select(db.Supplier))) == []
        assert session.execute(update(db.Supplier).values(name="Denied")).rowcount == 0
    with pytest.raises(DBAPIError):
        with Session(database.runtime) as session, session.begin():
            session.add(
                db.Item(organization_id=a.organization, item_code="DENIED", description="Denied")
            )


@pytest.mark.parametrize("rollback", [False, True])
def test_context_cannot_leak_on_reused_connection(database, tenants, rollback):
    a, b = tenants
    first_pid = None
    try:
        with tenant_session(database.runtime, a.organization) as session:
            first_pid = session.scalar(text("SELECT pg_backend_pid()"))
            assert session.get(db.Supplier, a.supplier) is not None
            if rollback:
                raise RuntimeError("Rollback this transaction")
    except RuntimeError:
        pass
    with database.runtime.connect() as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) == first_pid
        assert connection.scalar(
            text("SELECT current_setting(:setting, true)"), {"setting": TENANT_SETTING}
        ) in (None, "")
        assert connection.execute(select(db.Supplier)).all() == []
    with tenant_session(database.runtime, b.organization) as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == first_pid
        assert session.get(db.Supplier, a.supplier) is None
        assert session.get(db.Supplier, b.supplier) is not None


def test_composite_fk_blocks_cross_tenant_resolved_link_even_for_admin(database, tenants):
    a, b = tenants
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(invoice_line(a, resolved_purchase_order_line_id=b.po_line))


def test_composite_fk_blocks_cross_tenant_header(database, tenants):
    a, b = tenants
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(invoice_line(a, invoice_id=b.invoice))


def test_duplicate_invoice_occurrences_and_unresolved_references_are_preserved(database, tenants):
    a, _ = tenants
    with tenant_session(database.runtime, a.organization) as session:
        session.add_all([invoice_line(a), invoice_line(a, source_row_number=3)])
    with tenant_session(database.runtime, a.organization) as session:
        rows = list(
            session.scalars(select(db.InvoiceLine).where(db.InvoiceLine.invoice_id == a.invoice))
        )
        assert len(rows) == 2 and rows[0].id != rows[1].id
        assert all(
            row.line_number == 1 and row.resolved_purchase_order_line_id is None for row in rows
        )
        assert all(
            row.source_po_number == "UNKNOWN" and row.source_item_code == "WRONG-ITEM"
            for row in rows
        )


def test_business_discrepancies_are_not_rejected(database, tenants):
    a, _ = tenants
    with tenant_session(database.runtime, a.organization) as session:
        session.add(invoice_line(a, resolved_purchase_order_line_id=a.po_line))
        session.add(
            db.GoodsReceiptLine(
                organization_id=a.organization,
                goods_receipt_id=a.receipt,
                line_number=1,
                source_row_number=2,
                receipt_date=datetime.now(UTC).date(),
                source_po_number="UNKNOWN",
                source_po_line_number=99,
                source_item_code="OTHER",
                received_quantity=150,
                resolved_purchase_order_line_id=None,
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invoiced_quantity", Decimal(0)),
        ("invoiced_quantity", Decimal(-1)),
        ("invoiced_quantity", Decimal("NaN")),
        ("invoiced_quantity", Decimal("Infinity")),
        ("unit_price", Decimal(-1)),
        ("unit_price", Decimal("NaN")),
        ("unit_price", Decimal("Infinity")),
    ],
)
def test_financial_check_constraints(database, tenants, field, value):
    a, _ = tenants
    with pytest.raises(IntegrityError):
        with tenant_session(database.runtime, a.organization) as session:
            session.add(invoice_line(a, **{field: value}))


def test_numeric_round_trip_does_not_truncate_scale(database, tenants):
    a, _ = tenants
    price = Decimal("123456789.123456789123456789")
    with tenant_session(database.runtime, a.organization) as session:
        row = invoice_line(a, unit_price=price)
        session.add(row)
        session.flush()
        row_id = row.id
    with tenant_session(database.runtime, a.organization) as session:
        assert session.get(db.InvoiceLine, row_id).unit_price == price


def test_logical_po_line_uniqueness(database, tenants):
    a, _ = tenants
    with pytest.raises(IntegrityError):
        with tenant_session(database.runtime, a.organization) as session:
            session.add(
                db.PurchaseOrderLine(
                    organization_id=a.organization,
                    purchase_order_id=a.po,
                    line_number=1,
                    source_row_number=3,
                    source_item_code="ITEM",
                    description="duplicate",
                    ordered_quantity=1,
                    unit_price=0,
                )
            )


@pytest.mark.parametrize("slug", ["Bad Slug", "", " spaced "])
def test_organization_slug_validation(database, slug):
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(db.Organization(name="Example", slug=slug))


def test_organization_slug_unique(database, tenants):
    a, _ = tenants
    with Session(database.admin) as session:
        slug = session.get(db.Organization, a.organization).slug
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(db.Organization(name="Duplicate", slug=slug))


def test_membership_uniqueness_and_creator_ownership(database, tenants):
    a, b = tenants
    with Session(database.admin) as session, session.begin():
        user = db.User(email=f"{uuid4().hex}@example.test", display_name="Tester")
        session.add(user)
        session.flush()
        user_id = user.id
        session.add(
            db.OrganizationMembership(
                organization_id=a.organization, user_id=user_id, role=db.MembershipRole.MEMBER
            )
        )
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(
                db.OrganizationMembership(
                    organization_id=a.organization, user_id=user_id, role=db.MembershipRole.MEMBER
                )
            )
    with pytest.raises(IntegrityError):
        with Session(database.admin) as session, session.begin():
            session.add(
                db.AnalysisRun(
                    organization_id=b.organization,
                    analysis_mode=db.AnalysisMode.INVOICE_PO,
                    created_by_user_id=user_id,
                )
            )


@pytest.mark.parametrize(
    "value",
    [
        "bad",
        "sqlite:///test.db",
        "postgresql://u:secret@localhost/",
        "postgresql://secret@host:bad/db",
    ],
)
def test_configuration_rejects_invalid_urls_without_credentials(value):
    with pytest.raises(ValueError) as error:
        database_url(value)
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_snapshot_is_versioned_and_immutable(database, tenants):
    a, _ = tenants
    now = datetime.now(UTC)
    with tenant_session(database.runtime, a.organization) as session:
        run = db.AnalysisRun(
            organization_id=a.organization,
            analysis_mode=db.AnalysisMode.INVOICE_PO,
            status=db.RunStatus.COMPLETED,
            started_at=now,
            completed_at=now,
        )
        session.add(run)
        session.flush()
        snapshot = db.ResultSnapshot(
            organization_id=a.organization,
            analysis_run_id=run.id,
            schema_version=1,
            engine_version="0.1.0",
            report={"mode": "invoice-po", "summary": {}, "results": []},
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
    with pytest.raises(DBAPIError):
        with tenant_session(database.runtime, a.organization) as session:
            session.execute(
                update(db.ResultSnapshot)
                .where(db.ResultSnapshot.id == snapshot_id)
                .values(engine_version="changed")
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with database.admin.begin() as connection:
            connection.execute(delete(db.ResultSnapshot).where(db.ResultSnapshot.id == snapshot_id))


def test_runtime_has_no_identity_or_destructive_privileges(database):
    with database.runtime.connect() as connection:
        for table in Base.metadata.tables:
            assert not connection.scalar(
                text("SELECT has_table_privilege(current_user, :table, 'DELETE')"), {"table": table}
            )
            assert not connection.scalar(
                text("SELECT has_table_privilege(current_user, :table, 'TRUNCATE')"),
                {"table": table},
            )
        assert not connection.scalar(
            text("SELECT has_table_privilege(current_user, 'users', 'SELECT')")
        )
        assert not connection.scalar(
            text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        )


def test_business_history_restricts_organization_deletion(database, tenants):
    a, _ = tenants
    with pytest.raises(IntegrityError):
        with database.admin.begin() as connection:
            connection.execute(delete(db.Organization).where(db.Organization.id == a.organization))
