from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import register, sign_in, upload_files
from test_inventory import create_item, create_location, login, movement, seed_user

from reconcile.analysis.models import REQUIRED_SOURCES, AnalysisMode
from reconcile.auth.config import AUTH_PATH, CSRF_HEADER
from reconcile.persistence import models as db
from reconcile.persistence.audit import AuditEvent
from reconcile.web.paths import INTELLIGENCE_PATH, RUNS_PATH

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def csrf(client):
    return {CSRF_HEADER: client.get(f"{AUTH_PATH}/csrf").json()["csrf_token"]}


def create_run(auth, mode=AnalysisMode.THREE_WAY):
    files = upload_files()
    response = auth[1].post(
        f"{RUNS_PATH}/{mode}",
        files={key: files[key] for key in REQUIRED_SOURCES[mode]},
        headers=csrf(auth[1]),
    )
    assert response.status_code == 201, response.text
    return response.json()["run"]


def path(run, resource):
    return f"{INTELLIGENCE_PATH}/runs/{run['id']}/{resource}"


def context(auth):
    raw = auth[1].cookies.get(auth[0].settings.session_cookie)
    principal = auth[0].sessions.authenticate(raw)
    return raw, principal.active_organization_id, principal.user_id


def test_intelligence_permission_is_explicit_and_rechecked(auth, database):
    sign_in(auth)
    _, organization, _ = context(auth)
    run = create_run(auth)
    ap_email, ap_user = seed_user(auth, database, organization, db.MembershipRole.AP_MANAGER)
    member_email, _ = seed_user(auth, database, organization, db.MembershipRole.MEMBER)

    login(auth, ap_email)
    assert auth[1].get(path(run, "procurement")).status_code == 200
    assert auth[1].get(path(run, "suppliers")).status_code == 200
    assert auth[1].get(f"{INTELLIGENCE_PATH}/inventory").status_code == 200

    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.user_id == ap_user,
            )
            .values(role=db.MembershipRole.MEMBER)
        )
    assert auth[1].get(path(run, "procurement")).status_code == 403

    login(auth, member_email)
    assert auth[1].get(path(run, "procurement")).status_code == 403
    assert auth[1].get(path(run, "suppliers")).status_code == 403
    assert auth[1].get(f"{INTELLIGENCE_PATH}/inventory").status_code == 403


def test_selected_run_scope_archives_and_cross_tenant_uuid_hiding(auth, database):
    first_email, _ = sign_in(auth)
    first_run = create_run(auth)
    duplicate_run = create_run(auth)

    first = auth[1].get(path(first_run, "procurement")).json()
    duplicate = auth[1].get(path(duplicate_run, "procurement")).json()
    assert first["scope"] == duplicate["scope"] == "selected_run"
    assert (
        first["documents"]
        == duplicate["documents"]
        == {
            "purchase_orders": 13,
            "goods_receipts": 14,
            "invoices": 15,
        }
    )
    assert (
        first["lines"]
        == duplicate["lines"]
        == {
            "purchase_orders": 14,
            "goods_receipts": 15,
            "invoices": 17,
        }
    )
    assert first["money"] == duplicate["money"]

    _, organization, _ = context(auth)
    with Session(database.admin) as session, session.begin():
        run = session.get(db.AnalysisRun, UUID(first_run["id"]))
        run.archived_at = auth[3]()
    archived = auth[1].get(path(first_run, "procurement"))
    assert archived.status_code == 200 and archived.json()["run"]["archived"] is True

    second_email = register(auth)
    sign_in(auth, email=second_email)
    other_run = create_run(auth)
    sign_in(auth, email=first_email)
    assert auth[1].get(path(other_run, "procurement")).status_code == 404
    assert auth[1].get(path(other_run, "suppliers")).status_code == 404

    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count(db.AnalysisRun.id)).where(
                    db.AnalysisRun.organization_id == organization
                )
            )
            == 2
        )


@pytest.mark.parametrize(
    ("mode", "availability", "unavailable"),
    [
        (
            AnalysisMode.INVOICE_PO,
            (True, False, True),
            ("goods_receipts", "fulfillment"),
        ),
        (
            AnalysisMode.INVOICE_RECEIPT,
            (False, True, True),
            ("purchase_orders", "fulfillment"),
        ),
        (
            AnalysisMode.PO_RECEIPT,
            (True, True, False),
            ("invoices", "invoiced_value_by_currency"),
        ),
        (
            AnalysisMode.THREE_WAY,
            (True, True, True),
            (),
        ),
    ],
)
def test_procurement_is_mode_aware(auth, mode, availability, unavailable):
    sign_in(auth)
    payload = auth[1].get(path(create_run(auth, mode), "procurement")).json()
    assert tuple(payload["availability"].values()) == availability
    for name in unavailable:
        if name in payload["documents"]:
            assert payload["documents"][name] is None
            assert payload["lines"][name] is None
        elif name == "fulfillment":
            assert payload[name] is None
        else:
            assert payload["money"][name] is None
    for amounts in payload["money"].values():
        if amounts is not None:
            assert all(isinstance(amount, str) for amount in amounts.values())


def test_supplier_breakdown_preserves_source_identity_and_snapshot_semantics(auth):
    sign_in(auth)
    run = create_run(auth)
    response = auth[1].get(path(run, "suppliers"), params={"limit": 2})
    assert response.status_code == 200, response.text
    first_page = response.json()
    assert first_page["scope"] == "selected_run"
    assert len(first_page["items"]) == 2 and first_page["next_cursor"]
    assert all(item["identity"]["resolved"] is False for item in first_page["items"])
    assert all(item["identity"]["supplier_name"] is None for item in first_page["items"])

    second_page = auth[1].get(
        path(run, "suppliers"), params={"limit": 2, "cursor": first_page["next_cursor"]}
    )
    assert second_page.status_code == 200
    first_codes = {item["identity"]["supplier_code"] for item in first_page["items"]}
    second_codes = {item["identity"]["supplier_code"] for item in second_page.json()["items"]}
    assert first_codes.isdisjoint(second_codes)

    all_items = auth[1].get(path(run, "suppliers"), params={"limit": 100}).json()["items"]
    assert all_items
    assert any(sum(item["issues"]["by_code"].values()) > 0 for item in all_items)
    assert any(item["receiving"]["PARTIALLY_RECEIVED"] > 0 for item in all_items)
    for item in all_items:
        timing = item["receipt_timing"]
        assert timing["basis"] == "observed_in_selected_run_source_set"
        assert timing["first_receipt_eligible_line_count"] >= 0
        if timing["first_receipt_eligible_line_count"] == 0:
            assert timing["median_observed_days_to_first_receipt"] is None
        for amounts in (
            item["purchase_orders"]["ordered_value_by_currency"],
            item["invoices"]["invoiced_value_by_currency"],
        ):
            assert all(isinstance(amount, str) for amount in amounts.values())


def test_inventory_uses_only_ledger_and_half_open_occurred_window(auth, database):
    sign_in(auth)
    _, organization, _ = context(auth)
    run = create_run(auth)
    assert auth[1].get(path(run, "procurement")).status_code == 200
    empty = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()
    assert empty["items"] == []

    item = create_item(auth[1], "INTEL-1", "EA")
    location = create_location(auth[1], "INTEL-MAIN")
    inside = (auth[3]() - timedelta(days=6)).isoformat()
    outside = (auth[3]() - timedelta(days=8)).isoformat()
    assert (
        movement(
            auth[1],
            "OPENING_BALANCE",
            item["id"],
            location["id"],
            "10.50",
            occurred_at=outside,
        ).status_code
        == 201
    )
    assert (
        movement(
            auth[1],
            "STOCK_RECEIPT",
            item["id"],
            location["id"],
            "2.25",
            occurred_at=inside,
        ).status_code
        == 201
    )

    seven = auth[1].get(f"{INTELLIGENCE_PATH}/inventory", params={"window": "7d"}).json()
    thirty = auth[1].get(f"{INTELLIGENCE_PATH}/inventory", params={"window": "30d"}).json()
    row = seven["items"][0]
    assert seven["period"]["time_field"] == "occurred_at"
    assert row["current_on_hand"] == "12.75"
    assert row["operation_count"] == 1
    assert row["net_ledger_quantity_delta"] == "2.25"
    assert thirty["items"][0]["operation_count"] == 2
    assert thirty["items"][0]["net_ledger_quantity_delta"] == "12.75"
    assert seven["summary"]["operation_counts_by_type"]["STOCK_RECEIPT"] == 1
    assert seven["summary"]["operation_counts_by_type"]["OPENING_BALANCE"] == 0

    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count(db.StockMovement.id)).where(
                    db.StockMovement.organization_id == organization
                )
            )
            == 2
        )


def test_intelligence_reads_do_not_mutate_persisted_state(auth, database, monkeypatch):
    sign_in(auth)
    _, organization, _ = context(auth)
    run = create_run(auth)
    tables = (
        db.SourceFile,
        db.AnalysisRun,
        db.ResultSnapshot,
        db.Finding,
        db.Supplier,
        db.Item,
        db.InventoryLocation,
        db.InventoryOperation,
        db.StockMovement,
        AuditEvent,
    )

    def counts():
        with Session(database.admin) as session:
            return {
                table.__tablename__: session.scalar(
                    select(func.count(table.id)).where(table.organization_id == organization)
                )
                for table in tables
            }

    before = counts()
    monkeypatch.setattr(
        "reconcile.web.runs.render_records",
        lambda *_: pytest.fail("Intelligence reads must not run reconciliation."),
    )
    assert auth[1].get(path(run, "procurement")).status_code == 200
    assert auth[1].get(path(run, "suppliers")).status_code == 200
    assert auth[1].get(f"{INTELLIGENCE_PATH}/inventory").status_code == 200
    assert counts() == before


def test_intelligence_parameters_are_bounded(auth):
    sign_in(auth)
    run = create_run(auth)
    assert auth[1].get(path(run, "suppliers"), params={"limit": 101}).status_code == 422
    assert auth[1].get(path(run, "suppliers"), params={"cursor": "%%%"}).status_code == 400
    assert (
        auth[1].get(f"{INTELLIGENCE_PATH}/inventory", params={"window": "all"}).status_code == 422
    )
    invalid_uuid_cursor = "WyJBIiwiQiIsIm5vdC1hLXV1aWQiLCJhbHNvLWJhZCJd"
    assert (
        auth[1]
        .get(f"{INTELLIGENCE_PATH}/inventory", params={"cursor": invalid_uuid_cursor})
        .status_code
        == 400
    )


def test_supplier_queries_are_page_constant_and_reads_stay_bounded(auth, database):
    sign_in(auth)
    run = create_run(auth)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(database.runtime, "before_cursor_execute", capture)
    try:
        counts = []
        for limit in (1, 10):
            statements.clear()
            response = auth[1].get(path(run, "suppliers"), params={"limit": limit})
            assert response.status_code == 200
            counts.append(len(statements))
        assert counts[0] == counts[1]
        assert counts[0] <= 12

        statements.clear()
        assert auth[1].get(path(run, "procurement")).status_code == 200
        assert len(statements) <= 12
        statements.clear()
        assert auth[1].get(f"{INTELLIGENCE_PATH}/inventory").status_code == 200
        assert len(statements) <= 10
    finally:
        event.remove(database.runtime, "before_cursor_execute", capture)
