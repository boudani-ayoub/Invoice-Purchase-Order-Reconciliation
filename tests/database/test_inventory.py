from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_auth import PASSWORD, post, sign_in, upload_files
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture

from reconcile.auth.config import AUTH_PATH, CSRF_HEADER
from reconcile.auth.service_errors import AuthError
from reconcile.persistence import models as db
from reconcile.persistence.auth_models import UserCredential
from reconcile.persistence.session import TENANT_SETTING

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture
INVENTORY_PATH = "/api/v1/inventory"


def csrf(client):
    return {CSRF_HEADER: client.get(f"{AUTH_PATH}/csrf").json()["csrf_token"]}


def write(client, method, path, body):
    return client.request(method, f"{INVENTORY_PATH}{path}", json=body, headers=csrf(client))


def inventory_context(auth):
    _, raw = sign_in(auth)
    principal = auth[0].sessions.authenticate(raw)
    return raw, principal.active_organization_id, principal.user_id


def seed_user(auth, database, organization_id, role):
    email = f"inventory-{uuid4().hex}@example.com"
    with Session(database.admin) as session, session.begin():
        user = db.User(
            email=email,
            display_name="Inventory user",
            email_verified_at=auth[3](),
        )
        session.add(user)
        session.flush()
        session.add_all(
            [
                UserCredential(
                    user_id=user.id,
                    password_hash=auth[0].accounts.passwords.hash(PASSWORD),
                    password_updated_at=auth[3](),
                ),
                db.OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user.id,
                    role=role,
                ),
            ]
        )
        return email, user.id


def login(auth, email):
    response = post(auth[1], "login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return auth[1].cookies.get(auth[0].settings.session_cookie)


def create_item(client, code="SKU-1", uom="EA"):
    response = write(
        client,
        "POST",
        "/items",
        {"item_code": code, "description": f"{code} description", "base_uom": uom},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_location(client, code="MAIN"):
    response = write(client, "POST", "/locations", {"location_code": code, "name": f"{code} store"})
    assert response.status_code == 201, response.text
    return response.json()


def movement(client, kind, item_id, location_id, quantity, *, key=None, **extra):
    return write(
        client,
        "POST",
        "/movements",
        {
            "idempotency_key": str(key or uuid4()),
            "type": kind,
            "item_id": item_id,
            "location_id": location_id,
            "quantity": quantity,
            **extra,
        },
    )


def test_inventory_permissions_are_explicit_and_live(auth, database):
    _, organization_id, _ = inventory_context(auth)
    ap_email, ap_user = seed_user(auth, database, organization_id, db.MembershipRole.AP_MANAGER)
    member_email, _ = seed_user(auth, database, organization_id, db.MembershipRole.MEMBER)

    login(auth, ap_email)
    assert auth[1].get(f"{INVENTORY_PATH}/items").status_code == 200
    assert (
        write(
            auth[1],
            "POST",
            "/items",
            {"item_code": "DENIED", "description": "Denied", "base_uom": "EA"},
        ).status_code
        == 403
    )
    with Session(database.admin) as session, session.begin():
        session.execute(
            update(db.OrganizationMembership)
            .where(
                db.OrganizationMembership.organization_id == organization_id,
                db.OrganizationMembership.user_id == ap_user,
            )
            .values(role=db.MembershipRole.MEMBER)
        )
    assert auth[1].get(f"{INVENTORY_PATH}/items").status_code == 403

    login(auth, member_email)
    assert auth[1].get(f"{INVENTORY_PATH}/balances").status_code == 403
    assert (
        write(
            auth[1],
            "POST",
            "/locations",
            {"location_code": "MEMBER", "name": "Denied"},
        ).status_code
        == 403
    )


def test_archived_membership_is_denied_immediately(auth, database):
    _, organization_id, _ = inventory_context(auth)
    email, user_id = seed_user(auth, database, organization_id, db.MembershipRole.ORG_ADMIN)
    login(auth, email)
    assert auth[1].get(f"{INVENTORY_PATH}/items").status_code == 200

    with Session(database.admin) as session, session.begin():
        membership = session.scalar(
            select(db.OrganizationMembership).where(
                db.OrganizationMembership.organization_id == organization_id,
                db.OrganizationMembership.user_id == user_id,
            )
        )
        membership.status = db.RecordStatus.ARCHIVED

    assert auth[1].get(f"{INVENTORY_PATH}/items").status_code == 403


def test_master_data_versions_archive_rules_and_cross_tenant_hiding(auth, database):
    inventory_context(auth)
    item = create_item(auth[1])
    location = create_location(auth[1])
    assert item["base_uom"] == "EA" and item["version"] == 1
    assert (
        write(
            auth[1],
            "PATCH",
            f"/items/{item['id']}",
            {"expected_version": 1, "base_uom": "kg", "description": "Updated"},
        ).json()["base_uom"]
        == "KG"
    )
    assert (
        write(
            auth[1],
            "PATCH",
            f"/items/{item['id']}",
            {"expected_version": 1, "description": "Stale"},
        ).status_code
        == 409
    )
    archived_item = write(
        auth[1],
        "POST",
        f"/items/{item['id']}/archive",
        {"expected_version": 2},
    )
    assert archived_item.status_code == 200 and archived_item.json()["status"] == "ARCHIVED"
    restored_item = write(
        auth[1],
        "POST",
        f"/items/{item['id']}/restore",
        {"expected_version": 3},
    )
    assert restored_item.status_code == 200 and restored_item.json()["status"] == "ACTIVE"

    assert (
        write(
            auth[1],
            "POST",
            f"/locations/{location['id']}/archive",
            {"expected_version": 1},
        ).status_code
        == 200
    )
    restored = write(
        auth[1],
        "POST",
        f"/locations/{location['id']}/restore",
        {"expected_version": 2},
    )
    assert restored.status_code == 200 and restored.json()["status"] == "ACTIVE"

    foreign = db.Organization(name="Foreign", slug=f"foreign-{uuid4().hex}")
    with Session(database.admin) as session, session.begin():
        session.add(foreign)
        session.flush()
        foreign_item = db.Item(
            organization_id=foreign.id,
            item_code="SKU-1",
            description="Foreign",
            base_uom="EA",
        )
        session.add(foreign_item)
        session.flush()
        foreign_id = foreign_item.id
    assert auth[1].get(f"{INVENTORY_PATH}/items/{foreign_id}").status_code == 404


def test_master_codes_duplicates_and_database_immutability(auth, database):
    _, _, _ = inventory_context(auth)
    item = create_item(auth[1], "IMMUTABLE-CODE")
    location = create_location(auth[1], "IMMUTABLE-CODE")
    assert (
        write(
            auth[1],
            "POST",
            "/items",
            {
                "item_code": "IMMUTABLE-CODE",
                "description": "Duplicate",
                "base_uom": "EA",
            },
        ).status_code
        == 409
    )
    assert (
        write(
            auth[1],
            "POST",
            "/locations",
            {"location_code": "immutable-code", "name": "Duplicate"},
        ).status_code
        == 409
    )
    renamed = write(
        auth[1],
        "PATCH",
        f"/locations/{location['id']}",
        {"expected_version": 1, "name": "Renamed store"},
    )
    assert renamed.status_code == 200 and renamed.json()["version"] == 2
    assert (
        write(
            auth[1],
            "PATCH",
            f"/locations/{location['id']}",
            {"expected_version": 1, "name": "Stale rename"},
        ).status_code
        == 409
    )
    for model, identifier, values in (
        (db.Item, item["id"], {"item_code": "REWRITTEN"}),
        (db.InventoryLocation, location["id"], {"location_code": "REWRITTEN"}),
    ):
        with Session(database.admin) as session, pytest.raises(DBAPIError), session.begin():
            session.execute(update(model).where(model.id == identifier).values(**values))


def test_organization_switch_scopes_masters_balances_and_history(auth, database):
    _, first_organization, actor = inventory_context(auth)
    first_item = create_item(auth[1], "SHARED")
    first_location = create_location(auth[1], "SHARED")
    assert (
        movement(auth[1], "STOCK_RECEIPT", first_item["id"], first_location["id"], "2").status_code
        == 201
    )
    with Session(database.admin) as session, session.begin():
        second = db.Organization(name="Inventory second", slug=f"inventory-{uuid4().hex}")
        session.add(second)
        session.flush()
        second_id = second.id
        session.add(
            db.OrganizationMembership(
                organization_id=second_id,
                user_id=actor,
                role=db.MembershipRole.ORG_ADMIN,
            )
        )

    assert (
        post(auth[1], "select-organization", {"organization_id": str(second_id)}).status_code == 200
    )
    assert auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"] == []
    assert auth[1].get(f"{INVENTORY_PATH}/operations").json()["items"] == []
    assert auth[1].get(f"{INVENTORY_PATH}/items/{first_item['id']}").status_code == 404
    second_item = create_item(auth[1], "SHARED")
    second_location = create_location(auth[1], "SHARED")
    assert (
        movement(
            auth[1], "STOCK_RECEIPT", second_item["id"], second_location["id"], "5"
        ).status_code
        == 201
    )

    assert (
        post(
            auth[1], "select-organization", {"organization_id": str(first_organization)}
        ).status_code
        == 200
    )
    balances = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    operations = auth[1].get(f"{INVENTORY_PATH}/operations").json()["items"]
    assert [row["quantity"] for row in balances] == ["2"]
    assert len(operations) == 1
    assert operations[0]["movements"][0]["item"]["id"] == first_item["id"]


def test_posting_signs_balances_transfer_reversal_and_idempotency(auth):
    inventory_context(auth)
    item = create_item(auth[1], "LEDGER")
    main = create_location(auth[1], "MAIN")
    workshop = create_location(auth[1], "WORKSHOP")
    opening_key = uuid4()
    opening = movement(
        auth[1], "OPENING_BALANCE", item["id"], main["id"], "10.500", key=opening_key
    )
    assert opening.status_code == 201
    replay = movement(auth[1], "OPENING_BALANCE", item["id"], main["id"], "10.500", key=opening_key)
    assert replay.status_code == 200 and replay.json()["id"] == opening.json()["id"]
    assert movement(auth[1], "OPENING_BALANCE", item["id"], main["id"], "10.500").status_code == 409
    assert movement(auth[1], "STOCK_RECEIPT", item["id"], main["id"], "2.25").status_code == 201
    assert movement(auth[1], "STOCK_ISSUE", item["id"], main["id"], "3.75").status_code == 201
    assert movement(auth[1], "ADJUSTMENT_IN", item["id"], main["id"], "1").status_code == 201
    assert movement(auth[1], "ADJUSTMENT_OUT", item["id"], main["id"], "20").status_code == 409

    transfer = write(
        auth[1],
        "POST",
        "/transfers",
        {
            "idempotency_key": str(uuid4()),
            "item_id": item["id"],
            "source_location_id": main["id"],
            "destination_location_id": workshop["id"],
            "quantity": "4",
        },
    )
    assert transfer.status_code == 201
    assert sorted(line["quantity_delta"] for line in transfer.json()["movements"]) == ["-4", "4"]
    reversed_transfer = write(
        auth[1],
        "POST",
        f"/operations/{transfer.json()['id']}/reverse",
        {"idempotency_key": str(uuid4()), "note": "Wrong destination"},
    )
    assert reversed_transfer.status_code == 201
    assert sorted(line["quantity_delta"] for line in reversed_transfer.json()["movements"]) == [
        "-4",
        "4",
    ]
    assert (
        write(
            auth[1],
            "POST",
            f"/operations/{transfer.json()['id']}/reverse",
            {"idempotency_key": str(uuid4())},
        ).status_code
        == 409
    )

    balances = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    current = {
        (row["item"]["item_code"], row["location"]["location_code"]): row["quantity"]
        for row in balances
    }
    assert current[("LEDGER", "MAIN")] == "10.000"
    assert current[("LEDGER", "WORKSHOP")] == "0"
    assert (
        write(
            auth[1],
            "PATCH",
            f"/items/{item['id']}",
            {"expected_version": 1, "base_uom": "BOX"},
        ).status_code
        == 409
    )
    assert (
        write(
            auth[1],
            "POST",
            f"/items/{item['id']}/archive",
            {"expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        write(
            auth[1],
            "POST",
            f"/locations/{main['id']}/archive",
            {"expected_version": 1},
        ).status_code
        == 409
    )


def test_archived_location_and_failed_transfers_leave_balances_unchanged(auth):
    inventory_context(auth)
    item = create_item(auth[1], "TRANSFER-GUARDS")
    source = create_location(auth[1], "SOURCE")
    destination = create_location(auth[1], "DESTINATION")
    archived = create_location(auth[1], "ARCHIVED")
    assert movement(auth[1], "OPENING_BALANCE", item["id"], source["id"], "4").status_code == 201
    assert (
        write(
            auth[1],
            "POST",
            f"/locations/{archived['id']}/archive",
            {"expected_version": 1},
        ).status_code
        == 200
    )
    assert movement(auth[1], "STOCK_RECEIPT", item["id"], archived["id"], "1").status_code == 409

    def transfer(source_id, destination_id, quantity):
        return write(
            auth[1],
            "POST",
            "/transfers",
            {
                "idempotency_key": str(uuid4()),
                "item_id": item["id"],
                "source_location_id": source_id,
                "destination_location_id": destination_id,
                "quantity": quantity,
            },
        )

    assert transfer(source["id"], source["id"], "1").status_code == 422
    assert transfer(source["id"], destination["id"], "5").status_code == 409
    assert transfer(source["id"], archived["id"], "1").status_code == 409
    balances = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    assert {row["location"]["location_code"]: row["quantity"] for row in balances} == {
        "SOURCE": "4"
    }


def test_reversal_rejects_negative_stock_and_can_reverse_an_outbound(auth):
    inventory_context(auth)
    item = create_item(auth[1], "REVERSAL-GUARD")
    location = create_location(auth[1], "REVERSAL-GUARD")
    opening = movement(auth[1], "OPENING_BALANCE", item["id"], location["id"], "10").json()
    issue = movement(auth[1], "STOCK_ISSUE", item["id"], location["id"], "7").json()
    blocked = write(
        auth[1],
        "POST",
        f"/operations/{opening['id']}/reverse",
        {"idempotency_key": str(uuid4())},
    )
    assert blocked.status_code == 409
    assert (
        auth[1]
        .get(f"{INVENTORY_PATH}/balances", params={"item_id": item["id"]})
        .json()["items"][0]["quantity"]
        == "3"
    )
    reversed_issue = write(
        auth[1],
        "POST",
        f"/operations/{issue['id']}/reverse",
        {"idempotency_key": str(uuid4())},
    )
    assert reversed_issue.status_code == 201
    assert reversed_issue.json()["movements"][0]["quantity_delta"] == "7"


def test_idempotency_rejects_changed_intent_and_actor(auth, database):
    _, organization_id, _ = inventory_context(auth)
    item = create_item(auth[1], "IDEMPOTENCY-GUARD")
    location = create_location(auth[1], "IDEMPOTENCY-GUARD")
    key = uuid4()
    assert (
        movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], "1", key=key).status_code
        == 201
    )
    assert (
        movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], "2", key=key).status_code
        == 409
    )
    second_email, _ = seed_user(auth, database, organization_id, db.MembershipRole.ORG_ADMIN)
    login(auth, second_email)
    assert (
        movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], "1", key=key).status_code
        == 409
    )


@pytest.mark.parametrize("quantity", [7, -1, "-1", "0", "NaN", "Infinity", "1e2", " 1"])
def test_quantity_requires_a_positive_plain_decimal_string(auth, quantity):
    inventory_context(auth)
    item = create_item(auth[1], f"Q-{uuid4().hex[:8]}")
    location = create_location(auth[1], f"Q-{uuid4().hex[:8]}")
    assert (
        movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], quantity).status_code == 422
    )


def test_future_time_and_dedicated_operation_routes(auth):
    inventory_context(auth)
    item = create_item(auth[1], "TIME")
    location = create_location(auth[1], "TIME")
    future = (auth[3]() + timedelta(seconds=1)).isoformat()
    assert (
        movement(
            auth[1],
            "STOCK_RECEIPT",
            item["id"],
            location["id"],
            "1",
            occurred_at=future,
        ).status_code
        == 422
    )
    past = (auth[3]() - timedelta(days=7)).isoformat()
    assert (
        movement(
            auth[1],
            "STOCK_RECEIPT",
            item["id"],
            location["id"],
            "1",
            occurred_at=past,
        ).status_code
        == 201
    )
    assert movement(auth[1], "TRANSFER", item["id"], location["id"], "1").status_code == 422


def test_unconfigured_item_and_malformed_cursors_are_rejected(auth):
    inventory_context(auth)
    item = create_item(auth[1], "NO-UOM", uom=None)
    location = create_location(auth[1], "NO-UOM")
    assert movement(auth[1], "OPENING_BALANCE", item["id"], location["id"], "1").status_code == 409
    for endpoint in ("items", "locations", "balances", "operations"):
        assert (
            auth[1].get(f"{INVENTORY_PATH}/{endpoint}", params={"cursor": "%%%"}).status_code == 422
        )


def test_concurrent_outbound_writers_never_oversell(auth):
    raw, _, _ = inventory_context(auth)
    item = create_item(auth[1], "CONCURRENT")
    location = create_location(auth[1], "CONCURRENT")
    assert movement(auth[1], "OPENING_BALANCE", item["id"], location["id"], "10").status_code == 201

    def issue():
        try:
            return (
                auth[0]
                .inventory.post_movement(
                    raw,
                    operation_type=db.InventoryOperationType.STOCK_ISSUE,
                    item_id=item["id"],
                    location_id=location["id"],
                    quantity=Decimal("7"),
                    occurred_at=None,
                    external_reference=None,
                    note=None,
                    idempotency_key=uuid4(),
                    request_id=uuid4(),
                )
                .created
            )
        except AuthError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))
    assert sorted(results, key=str) == [True, "insufficient_stock"]
    balance = (
        auth[1].get(f"{INVENTORY_PATH}/balances", params={"item_id": item["id"]}).json()["items"][0]
    )
    assert balance["quantity"] == "3"


def test_opposing_transfers_use_deadlock_safe_lock_order(auth):
    raw, _, _ = inventory_context(auth)
    item = create_item(auth[1], "OPPOSING")
    first = create_location(auth[1], "OPPOSING-A")
    second = create_location(auth[1], "OPPOSING-B")
    for location in (first, second):
        assert (
            movement(auth[1], "OPENING_BALANCE", item["id"], location["id"], "10").status_code
            == 201
        )

    def transfer(source_id, destination_id):
        return auth[0].inventory.transfer(
            raw,
            item_id=item["id"],
            source_location_id=source_id,
            destination_location_id=destination_id,
            quantity=Decimal("3"),
            occurred_at=None,
            external_reference=None,
            note=None,
            idempotency_key=uuid4(),
            request_id=uuid4(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(transfer, first["id"], second["id"]),
            pool.submit(transfer, second["id"], first["id"]),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert all(result.created for result in results)
    balances = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    assert {row["location"]["location_code"]: row["quantity"] for row in balances} == {
        "OPPOSING-A": "10",
        "OPPOSING-B": "10",
    }


def test_concurrent_same_key_creates_one_operation(auth, database):
    raw, organization_id, _ = inventory_context(auth)
    item = create_item(auth[1], "IDEMPOTENT")
    location = create_location(auth[1], "IDEMPOTENT")
    key = uuid4()

    def receive():
        return auth[0].inventory.post_movement(
            raw,
            operation_type=db.InventoryOperationType.STOCK_RECEIPT,
            item_id=item["id"],
            location_id=location["id"],
            quantity=Decimal("2.5"),
            occurred_at=None,
            external_reference=None,
            note=None,
            idempotency_key=key,
            request_id=uuid4(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: receive(), range(2)))
    assert {result.created for result in results} == {False, True}
    assert results[0].payload["id"] == results[1].payload["id"]
    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count(db.InventoryOperation.id)).where(
                    db.InventoryOperation.organization_id == organization_id,
                    db.InventoryOperation.idempotency_key == key,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(db.StockMovement.id)).where(
                    db.StockMovement.organization_id == organization_id,
                    db.StockMovement.item_id == item["id"],
                )
            )
            == 1
        )


def test_procurement_receipts_never_create_stock(auth, database):
    _, organization_id, _ = inventory_context(auth)
    before = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    for _ in range(2):
        response = auth[1].post(
            "/api/v1/runs/three-way", files=upload_files(), headers=csrf(auth[1])
        )
        assert response.status_code == 201, response.text
    after = auth[1].get(f"{INVENTORY_PATH}/balances").json()["items"]
    assert after == before
    with Session(database.admin) as session:
        assert (
            session.scalar(
                select(func.count(db.StockMovement.id)).where(
                    db.StockMovement.organization_id == organization_id
                )
            )
            == 0
        )


def test_ledger_is_immutable_and_missing_rls_context_fails_closed(auth, database):
    _, organization_id, _ = inventory_context(auth)
    item = create_item(auth[1], "IMMUTABLE")
    location = create_location(auth[1], "IMMUTABLE")
    operation = movement(auth[1], "STOCK_RECEIPT", item["id"], location["id"], "1").json()
    movement_id = operation["movements"][0]["id"]

    for statement in (
        update(db.InventoryOperation)
        .where(db.InventoryOperation.id == operation["id"])
        .values(note="rewritten"),
        delete(db.InventoryOperation).where(db.InventoryOperation.id == operation["id"]),
        update(db.StockMovement).where(db.StockMovement.id == movement_id).values(quantity_delta=2),
        delete(db.StockMovement).where(db.StockMovement.id == movement_id),
    ):
        with Session(database.admin) as session, pytest.raises(DBAPIError), session.begin():
            session.execute(statement)

    with database.runtime.connect() as connection:
        assert connection.scalar(select(func.count(db.StockMovement.id))) == 0
        connection.execute(
            text("SELECT set_config(:setting, :organization, true)"),
            {"setting": TENANT_SETTING, "organization": str(organization_id)},
        )
        assert connection.scalar(select(func.count(db.StockMovement.id))) == 1
