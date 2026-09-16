import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_auth import sign_in

from reconcile.persistence import models as db
from reconcile.persistence.intelligence import inventory_operation_counts_query
from reconcile.persistence.intelligence_policy import IntelligenceWindow, Period

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture


def test_inventory_window_query_plan_uses_measured_occurred_time_index(auth, database):
    _, raw = sign_in(auth)
    principal = auth[0].sessions.authenticate(raw)
    organization = principal.active_organization_id
    actor = principal.user_id
    now = auth[3]()
    records = []
    for index in range(20_000):
        records.append(
            {
                "id": uuid4(),
                "organization_id": organization,
                "operation_type": "STOCK_RECEIPT",
                "actor_user_id": actor,
                "occurred_at": now - timedelta(days=index % 365, seconds=1),
                "created_at": now,
                "updated_at": now,
                "external_reference": None,
                "note": None,
                "request_id": uuid4(),
                "idempotency_key": uuid4(),
                "request_fingerprint": f"{index:064x}",
                "reverses_operation_id": None,
            }
        )
    period = Period.at(IntelligenceWindow.MONTH, now)
    query = inventory_operation_counts_query(organization, period)
    with database.admin.connect() as connection, connection.begin() as transaction:
        connection.execute(
            text("ALTER TABLE inventory_operations DISABLE TRIGGER validate_inventory_operation")
        )
        connection.execute(insert(db.InventoryOperation.__table__), records)
        connection.execute(text("ANALYZE inventory_operations"))
        connection.execute(text("DROP INDEX ix_inventory_operations_intelligence_window"))

        def plan():
            connection.execute(text("SET LOCAL ROLE reconcile_runtime"))
            connection.execute(
                text("SELECT set_config('app.current_organization_id', :org, true)"),
                {"org": str(organization)},
            )
            sql = str(
                query.compile(
                    dialect=connection.dialect,
                    compile_kwargs={"literal_binds": True},
                )
            )
            result = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            ).scalar_one()[0]
            connection.execute(text("RESET ROLE"))
            return result

        before = plan()
        connection.execute(
            text(
                "CREATE INDEX ix_inventory_operations_intelligence_window "
                "ON inventory_operations (organization_id, occurred_at, operation_type)"
            )
        )
        after = plan()
        print(
            json.dumps(
                {
                    "query": "inventory_operation_counts",
                    "before_execution_ms": before["Execution Time"],
                    "indexed_execution_ms": after["Execution Time"],
                }
            )
        )
        assert "ix_inventory_operations_intelligence_window" in json.dumps(after)
        assert after["Plan"]["Actual Rows"] == before["Plan"]["Actual Rows"]
        transaction.rollback()
