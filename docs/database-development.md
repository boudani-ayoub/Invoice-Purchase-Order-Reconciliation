# PostgreSQL development and verification

The stateless CLI, FastAPI application, and browser workflows never connect to PostgreSQL. Install
the database extra only when working on persistence:

```bash
python -m pip install -e ".[dev,web,db]"
```

Use a supported PostgreSQL 17 server (the CI service uses major 17). The foundation uses SQLAlchemy
2.0, Alembic, and psycopg 3. `DATABASE_URL` accepts `postgresql://` or `postgresql+psycopg://` and
selects psycopg explicitly. It is private server configuration; never use a `NEXT_PUBLIC_*` name.
Configuration failures omit the supplied URL. SQLAlchemy hides bound parameters in errors.

## Provisioning and migrations

An administrator provisions a database owned by a dedicated schema/migration role, a runtime
login, and a `reconcile_runtime` NOLOGIN privilege group. Neither application nor schema-owner
login should be superuser/BYPASSRLS. Choose real credentials through your secret-management
process. Grant `reconcile_runtime` membership to the runtime login; do not grant it membership in
the schema-owner role. The runtime login must not own the database or schema.

Use the schema-owner connection in private `DATABASE_URL`, then run from the checkout or unpacked
source distribution:

```bash
alembic upgrade head
alembic check
```

The migration installs all 16 tables, checks, foreign keys, indexes, RLS policies, timestamp triggers,
snapshot protection, and runtime grants. No manual table/policy setup is needed. Role provisioning
is deliberately separate from migrations: application migrations should not require CREATEROLE.
The source distribution contains Alembic assets; the core wheel remains lightweight and DB-free.

Run future application persistence code using the runtime connection, never the schema-owner URL.
`tenant_session(engine, verified_organization_uuid)` starts a transaction, binds transaction-local
context, commits success and rolls back failure. It does **not** verify membership. Phase 2 must
perform that check before using this internal helper. No HTTP route calls it in Phase 1.

## Integration tests

Set `TEST_DATABASE_ADMIN_URL` to an explicitly disposable local/CI PostgreSQL administrator
connection. Unlike `DATABASE_URL`, this test setting must permit creating/dropping databases and
roles. Tests create a uniquely named `reconcile_test_*` database, migration owner, and runtime
login; migrate as the owner; test RLS as the separate runtime login; then dispose connections and
drop only their generated database and roles. The NOLOGIN privilege group can remain for reuse.
Existing databases and records are not reset. Each case seeds fresh organizations.

```powershell
# Set TEST_DATABASE_ADMIN_URL privately for your local server before this command.
python -m pytest tests/database -vv
```

If no test URL or database extra is provided, database-dependent tests are explicitly skipped.
The CI PostgreSQL job supplies both and runs all database tests. SQLite is never substituted.
The CI password is a disposable service credential, not a deployed application secret.

## Local Windows binaries

An alternative to an installed service is the official
[EDB PostgreSQL binary archive](https://www.enterprisedb.com/download-postgresql-binaries).
Keep the extracted binaries, data, and logs outside source control. For this implementation's
verification they live under ignored `.local/`; the test listener uses loopback port 55432.

For a new private local test cluster, run the archive's `initdb` with `-D` pointing to a new data
directory, then `pg_ctl -D <data-directory> -l <log-file> -o "-h 127.0.0.1 -p <local-port>" start`.
Choose a free port and matching test URL. A local trust-authentication cluster is for disposable
tests only; do not expose it to other hosts or use it for customer data. Stop your test cluster
after use with `pg_ctl -D <data-directory> stop`. No Windows service is installed by this workflow.

## Evidence and limits

See [the phase report](product-phase-1-report.md) for actual tested versions and counts, and
[data-model-v1.md](data-model-v1.md) for ownership, immutable snapshots, duplicate preservation,
deletion rules, and unresolved references. Persistent imports, saved runs, and CRUD remain future
work, after authenticated authorization exists.
