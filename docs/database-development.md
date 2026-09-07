# PostgreSQL development and verification

The CLI remains database-independent. The web product requires PostgreSQL for identity and
sessions, but does not yet save financial uploads or analysis runs. Install the product extras:

```bash
python -m pip install -e ".[dev,web,db,auth]"
```

Use a supported PostgreSQL 17 server (the CI service uses major 17). The foundation uses SQLAlchemy
2.0, Alembic, and psycopg 3. `DATABASE_URL` accepts `postgresql://` or `postgresql+psycopg://` and
selects psycopg explicitly. It is private server configuration; never use a `NEXT_PUBLIC_*` name.
Configuration failures omit the supplied URL. SQLAlchemy hides bound parameters in errors.

## Provisioning and migrations

An administrator provisions a database owned by a dedicated schema/migration role, separate runtime
and identity logins, and `reconcile_runtime` / `reconcile_identity` NOLOGIN privilege groups. Neither application nor schema-owner
login should be superuser/BYPASSRLS. Choose real credentials through your secret-management
process. Grant `reconcile_runtime` membership to the runtime login; do not grant it membership in
the schema-owner role. Grant only `reconcile_identity` to the identity login. Never give either
HTTP login both groups, role creation, database creation, or ownership of the database/schema.
Grant CONNECT on the product database to both logins. Do not grant PUBLIC CREATE on its schema.

Example group provisioning (run as a database administrator; login names and credentials are
deployment choices):

```sql
CREATE ROLE reconcile_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE reconcile_identity NOLOGIN NOSUPERUSER NOBYPASSRLS;
```

If `reconcile_runtime` already exists from Phase 1, retain it. Create the identity group before
applying `0002`. The migration owner needs the existing runtime group to install the Phase 1
policies. HTTP startup verifies role flags, memberships, schema ownership, and forbidden grants.

Use the schema-owner connection in private `DATABASE_URL`, then run from the checkout or unpacked
source distribution:

```bash
alembic upgrade head
alembic check
```

The migrations install 20 tables, checks, foreign keys, indexes, RLS policies, timestamp triggers,
snapshot protection, and runtime grants. No manual table/policy setup is needed. Role provisioning
is deliberately separate from migrations: application migrations should not require CREATEROLE.
The source distribution contains Alembic assets; the core wheel remains lightweight and DB-free.

Migration `0001` is unchanged; `0002` adds credentials, hashed sessions, email tokens, throttle
buckets, and nullable `users.email_verified_at`. Existing Phase 1 users are preserved but are not
silently given a password or verified status. There is no legacy-account activation UI in Phase 2.

After migrating, run HTTP with the tenant login in `DATABASE_URL` and the identity login in
`IDENTITY_DATABASE_URL`, never the schema-owner URL. Do not reuse the migration process environment.
`tenant_session(engine, verified_organization_uuid)` starts a transaction, binds transaction-local
context, commits success and rolls back failure. It does **not** verify membership. Phase 2 checks
session, active user, active membership, and permission before entering this helper, then rechecks
membership and organization under tenant RLS. Identity policies apply only to the identity group;
all 20 tables keep ENABLE/FORCE RLS. No SECURITY DEFINER escape hatch is added.

## Integration tests

Set `TEST_DATABASE_ADMIN_URL` to an explicitly disposable local/CI PostgreSQL administrator
connection. Unlike `DATABASE_URL`, this test setting must permit creating/dropping databases and
roles. Tests create a uniquely named `reconcile_test_*` database and three logins: migration owner,
runtime, and identity. They migrate as the owner, exercise auth/RLS as the restricted logins,
then dispose connections and drop only their generated database and roles. NOLOGIN groups remain.
Existing databases and records are not reset. Each case seeds fresh organizations.

```powershell
# Set TEST_DATABASE_ADMIN_URL privately for your local server before this command.
python -m pytest tests/database -vv
```

If no test URL or database extra is provided, database-dependent tests are explicitly skipped.
The CI PostgreSQL job supplies the test URL and all extras. SQLite is never substituted.
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

The real-service browser runner also requires `TEST_DATABASE_ADMIN_URL`. It creates its own
disposable database with explicit development verification/mail settings; it does not mock auth.
For an interactive local check, run:

```bash
python -m scripts.product_e2e --host 127.0.0.1 --port 8010 --frontend-origin http://127.0.0.1:3010
```

Build Next with the matching API port.
Interrupt normally to permit cleanup. A forced process kill can leave uniquely named test
databases/roles for an administrator to inspect and remove; never reset unrelated databases.

See [the Phase 2 report](product-phase-2-report.md) for current tested versions and counts, and
[data-model-v1.md](data-model-v1.md) for ownership, immutable snapshots, duplicate preservation,
deletion rules, and unresolved references. Persistent imports, saved runs, and CRUD remain future
work, after authenticated authorization exists.
