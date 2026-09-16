from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import post, register, sign_in, upload_files
from test_inventory import create_item, create_location, login, movement, seed_user, write

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

    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == organization,
                db.OrganizationMembership.user_id == ap_user,
            )
            .values(role=db.MembershipRole.AP_MANAGER, status=db.RecordStatus.ARCHIVED)
        )
    assert auth[1].get(path(run, "procurement")).status_code == 403
    assert auth[1].get(path(run, "suppliers")).status_code == 403
    assert auth[1].get(f"{INTELLIGENCE_PATH}/inventory").status_code == 403

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


def test_organization_switch_changes_every_intelligence_scope(auth, database):
    sign_in(auth)
    _, first_organization, actor = context(auth)
    first_run = create_run(auth)
    first_item = create_item(auth[1], "FIRST-INTEL")
    first_location = create_location(auth[1], "FIRST-INTEL")
    assert (
        movement(auth[1], "STOCK_RECEIPT", first_item["id"], first_location["id"], "2").status_code
        == 201
    )

    with Session(database.admin) as session, session.begin():
        second = db.Organization(name="Second insights", slug=f"insights-{uuid4().hex}")
        session.add(second)
        session.flush()
        second_organization = second.id
        session.add(
            db.OrganizationMembership(
                organization_id=second_organization,
                user_id=actor,
                role=db.MembershipRole.ORG_ADMIN,
            )
        )

    assert (
        post(
            auth[1],
            "select-organization",
            {"organization_id": str(second_organization)},
        ).status_code
        == 200
    )
    assert auth[1].get(path(first_run, "procurement")).status_code == 404
    assert auth[1].get(path(first_run, "suppliers")).status_code == 404
    second_empty = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()
    assert second_empty["items"] == []
    assert second_empty["summary"]["positive_item_location_position_count"] == 0

    second_item = create_item(auth[1], "SECOND-INTEL")
    second_location = create_location(auth[1], "SECOND-INTEL")
    assert (
        movement(
            auth[1], "STOCK_RECEIPT", second_item["id"], second_location["id"], "5"
        ).status_code
        == 201
    )
    second_rows = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()["items"]
    assert [(row["item"]["item_code"], row["current_on_hand"]) for row in second_rows] == [
        ("SECOND-INTEL", "5")
    ]

    assert (
        post(
            auth[1],
            "select-organization",
            {"organization_id": str(first_organization)},
        ).status_code
        == 200
    )
    assert auth[1].get(path(first_run, "procurement")).status_code == 200
    first_rows = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()["items"]
    assert [(row["item"]["item_code"], row["current_on_hand"]) for row in first_rows] == [
        ("FIRST-INTEL", "2")
    ]


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
    by_code = {item["identity"]["supplier_code"]: item for item in all_items}
    partial_timing = by_code["SUP-BETA"]["receipt_timing"]
    assert partial_timing == {
        "median_observed_days_to_first_receipt": "3",
        "first_receipt_eligible_line_count": 1,
        "median_observed_days_to_full_receipt": None,
        "full_receipt_eligible_line_count": 0,
        "basis": "observed_in_selected_run_source_set",
    }
    no_receipt_timing = by_code["SUP-EPSILON"]["receipt_timing"]
    assert no_receipt_timing["median_observed_days_to_first_receipt"] is None
    assert no_receipt_timing["first_receipt_eligible_line_count"] == 0


def test_inventory_uses_only_ledger_and_half_open_occurred_window(auth, database):
    sign_in(auth)
    _, organization, _ = context(auth)
    run = create_run(auth)
    procurement_before = auth[1].get(path(run, "procurement")).json()
    empty = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()
    assert empty["items"] == []

    item = create_item(auth[1], "INTEL-1", "EA")
    location = create_location(auth[1], "INTEL-MAIN")
    now = auth[3]()
    inside = (now - timedelta(days=6)).isoformat()
    start = (now - timedelta(days=7)).isoformat()
    outside = (now - timedelta(days=8)).isoformat()
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
            "ADJUSTMENT_IN",
            item["id"],
            location["id"],
            "1",
            occurred_at=start,
        ).status_code
        == 201
    )
    assert (
        movement(
            auth[1],
            "ADJUSTMENT_IN",
            item["id"],
            location["id"],
            "3",
            occurred_at=now.isoformat(),
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
    assert seven["period"]["start"] == start
    assert seven["period"]["end"] == now.isoformat()
    assert row["current_on_hand"] == "16.75"
    assert row["operation_count"] == 2
    assert row["net_ledger_quantity_delta"] == "3.25"
    assert thirty["items"][0]["operation_count"] == 3
    assert thirty["items"][0]["net_ledger_quantity_delta"] == "13.75"
    assert seven["summary"]["operation_counts_by_type"]["STOCK_RECEIPT"] == 1
    assert seven["summary"]["operation_counts_by_type"]["OPENING_BALANCE"] == 0
    assert seven["summary"]["operation_counts_by_type"]["ADJUSTMENT_IN"] == 1
    assert "total_inventory_quantity" not in seven["summary"]
    assert "inventory_value" not in seven["summary"]
    assert auth[1].get(path(run, "procurement")).json() == procurement_before

    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count(db.StockMovement.id)).where(
                    db.StockMovement.organization_id == organization
                )
            )
            == 4
        )


def test_inventory_intelligence_keeps_transfer_and_reversal_operations_explicit(auth):
    sign_in(auth)
    item = create_item(auth[1], "INTEL-TRANSFER")
    source = create_location(auth[1], "INTEL-SOURCE")
    destination = create_location(auth[1], "INTEL-DESTINATION")
    assert movement(auth[1], "STOCK_RECEIPT", item["id"], source["id"], "10").status_code == 201
    transfer = write(
        auth[1],
        "POST",
        "/transfers",
        {
            "idempotency_key": str(uuid4()),
            "item_id": item["id"],
            "source_location_id": source["id"],
            "destination_location_id": destination["id"],
            "quantity": "4",
        },
    )
    assert transfer.status_code == 201
    reversal = write(
        auth[1],
        "POST",
        f"/operations/{transfer.json()['id']}/reverse",
        {"idempotency_key": str(uuid4())},
    )
    assert reversal.status_code == 201

    auth[3].now += timedelta(seconds=1)
    payload = auth[1].get(f"{INTELLIGENCE_PATH}/inventory").json()
    counts = payload["summary"]["operation_counts_by_type"]
    assert counts["STOCK_RECEIPT"] == 1
    assert counts["TRANSFER"] == 1
    assert counts["REVERSAL"] == 1
    assert payload["summary"]["reversal_operation_count"] == 1
    positions = {
        row["location"]["location_code"]: (
            row["current_on_hand"],
            row["operation_count"],
            row["net_ledger_quantity_delta"],
        )
        for row in payload["items"]
    }
    assert positions == {
        "INTEL-DESTINATION": ("0", 2, "0"),
        "INTEL-SOURCE": ("10", 3, "10"),
    }


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
