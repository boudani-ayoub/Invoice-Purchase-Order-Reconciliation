import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import insert, text
from test_auth import auth as auth_fixture
from test_auth import passwords as passwords_fixture
from test_dashboard import arrange, metric
from test_dashboard import dashboard as dashboard_fixture
from test_workflow import add_member

from reconcile.persistence.dashboard import overview_query, trends_query
from reconcile.persistence.dashboard_policy import Period, ReportingWindow
from reconcile.persistence.workflow_events import FindingEvent

pytestmark = pytest.mark.database
auth = auth_fixture
passwords = passwords_fixture
dashboard = dashboard_fixture


def test_workload_uses_one_aggregate_and_one_bounded_identity_lookup(auth, database, dashboard):
    _, rows, org, _ = dashboard
    for row in rows:
        arrange(database, row, status="OPEN", assignee_user_id=add_member(database, org))
    statements = []

    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    for engine in (database.runtime, database.identity):
        sql_event.listen(engine, "before_cursor_execute", record)
    try:
        assert len(metric(auth, "workload")["items"]) == len(rows)
    finally:
        for engine in (database.runtime, database.identity):
            sql_event.remove(engine, "before_cursor_execute", record)
    assert len([sql for sql in statements if "from findings" in sql]) == 1
    labels = [sql for sql in statements if "users.display_name" in sql and "users.id in" in sql]
    assert len(labels) == 1
    assert "organization_memberships.organization_id =" in labels[0]


def test_activity_query_plan_review(auth, database, dashboard):
    """Compare actual aggregate plans on synthetic, disposable event history."""
    _, rows, org, actor = dashboard
    now = auth[3].now
    records = []
    for i in range(20000):
        kind = "REOPENED" if i < 100 else "COMMENT_ADDED"
        when = now - timedelta(days=i % 365, seconds=1)
        records.append(
            {
                "id": uuid4(),
                "organization_id": org,
                "finding_id": UUID(rows[i % len(rows)]["id"]),
                "actor_user_id": actor,
                "request_id": uuid4(),
                "event_type": kind,
                "created_at": when,
                "updated_at": when,
                "message": "Synthetic query-plan fixture" if kind == "COMMENT_ADDED" else None,
                "metadata": {},
            }
        )
    period = Period.at(ReportingWindow.MONTH, now)
    queries = {"overview": overview_query(org, now, period), "trends": trends_query(org, period)}
    with database.admin.connect() as connection, connection.begin() as transaction:
        connection.execute(insert(FindingEvent.__table__), records)
        connection.execute(text("ANALYZE finding_events"))
        connection.execute(text("DROP INDEX ix_finding_events_activity"))

        def plans():
            connection.execute(text("SET LOCAL ROLE reconcile_runtime"))
            connection.execute(
                text("SELECT set_config('app.current_organization_id', :org, true)"),
                {"org": str(org)},
            )
            result = {}
            for name, query in queries.items():
                sql = str(
                    query.compile(
                        dialect=connection.dialect, compile_kwargs={"literal_binds": True}
                    )
                )
                result[name] = connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
                ).scalar_one()[0]
            connection.execute(text("RESET ROLE"))
            return result

        before = plans()
        connection.execute(
            text(
                "CREATE INDEX ix_finding_events_activity ON finding_events "
                "(organization_id, event_type, created_at)"
            )
        )
        after = plans()
        for name in queries:

            def summary(plan):
                return {
                    "execution_ms": plan["Execution Time"],
                    "shared_hit_blocks": plan["Plan"]["Shared Hit Blocks"],
                    "shared_read_blocks": plan["Plan"]["Shared Read Blocks"],
                    "rows": plan["Plan"]["Actual Rows"],
                }

            print(
                json.dumps(
                    {
                        "query": name,
                        "before": summary(before[name]),
                        "indexed": summary(after[name]),
                    }
                )
            )
            assert "ix_finding_events_activity" in json.dumps(after[name])
            assert after[name]["Plan"]["Actual Rows"] == before[name]["Plan"]["Actual Rows"]
        transaction.rollback()
