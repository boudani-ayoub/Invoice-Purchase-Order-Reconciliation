# Backup and restore runbook

## Scope and ownership

Persistent runs make PostgreSQL business data, not just identity state, a recovery concern.
Backups contain source records, financial reports, safe filenames/hashes, titles/notes, audit
actors, account data, invitation/governance history, and credential/session/token hashes. Raw uploaded CSV files are not retained by
the application, so a database backup cannot recover their original bytes.

This is an operator checklist, not an installed backup service. An operations owner must approve
frequency, retention, access, encryption/key recovery, off-host storage and monitoring before
customer use. Record recovery-point (acceptable lost time/data) and recovery-time targets; this
project supplies no numerical RPO/RTO guarantee. Periodic logical dumps alone do not provide
point-in-time recovery.

## Prepare and capture

1. Record database/server and client versions, deployed commit/package version, migration revision,
   backup start/end time and approved destination. Use a client compatible with the server.
2. Use a dedicated authorized backup operator capable of reading all required data despite forced
   RLS. Do not reuse the tenant/identity HTTP logins or weaken their policies for backup. Keep
   migration-owner/admin credentials out of the API environment.
3. Obtain connection credentials privately, preferably through a restricted password/service
   file or managed secret. Never put a password in a shell history, repository, issue or screenshot.
4. Write only to a new, access-restricted, encrypted staging destination. A custom dump is not
   encrypted merely because it is compressed. Encrypt off-host copies with recoverable separately
   controlled keys; verify transfer/checksum and restrict restore access.

For an approved connection supplied privately through libpq settings, this is the logical-dump
shape (replace the destination with a new approved path):

```text
pg_dump --format=custom --file=<new-restricted-backup-path>
pg_restore --list <restricted-backup-path>
```

Do not use `--enable-row-security` to silently accept a tenant-filtered partial backup. Capture
the role/ownership/grant provisioning needed for restoration separately: a single-database dump
does not include cluster-global role definitions. Inventory those definitions without publishing
credential hashes. PostgreSQL documents consistent logical dumps and global-role handling in
[SQL Dump](https://www.postgresql.org/docs/17/backup-dump.html).

## Restore in isolation first

1. Verify backup provenance/integrity. Treat a dump as executable database content; do not restore
   an untrusted archive with elevated privileges. Provision an empty isolated target from
   `template0`, on a compatible server, with no customer traffic or outgoing mail.
2. Recreate the reviewed schema-owner, runtime and identity groups/logins. Preserve separation:
   neither HTTP login may be owner/superuser/BYPASSRLS or a member of both privilege groups.
   Map ownership deliberately if restore names differ. Do not blanket-grant missing permissions.
3. Restore into that verified empty target and stop on errors. Do not use `--clean` against a live
   database. The approved operator supplies the target privately; review it before invocation.

```text
pg_restore --exit-on-error --single-transaction --dbname=<verified-empty-target> <restricted-backup-path>
```

For a deliberately different migration owner, `--no-owner` can assign restored objects to the
restoring role; review resulting owners and grants explicitly. Do not use `--no-acl` as a shortcut
around the runtime/identity contract. See the official
[pg_restore reference](https://www.postgresql.org/docs/17/app-pgrestore.html).

4. Check migration revision before starting the matching application. Run `alembic check`; if a
   later application needs upgrades, snapshot the restored target and migrate as its owner first.
5. Verify source/run/snapshot/audit/governance row counts, representative report JSON and hashes,
   same-tenant actor links, invitation lifecycle, and login/session behavior. Use a restricted
   synthetic account for browser checks.
6. Check every application table retains ENABLE/FORCE RLS; snapshot, run-audit, workflow,
   governance, inventory-ledger, and inventory-validation triggers/checks are present; the dashboard
   activity and inventory intelligence-window indexes exist; runtime cannot DELETE/TRUNCATE or
   rewrite evidence/audit/ledger rows; and identity cannot read procurement, workflow, inventory,
   or intelligence source state.
   Reads without tenant context must return no tenant history; cross-tenant GET/PATCH/archive
   must return `404`. Confirm owner credentials are absent from HTTP startup.
7. Verify session/recovery-token invalidation policy with the incident owner. Restoring old auth
   state can restore previously valid credentials, sessions, or unexpired invitation tokens; do
   not expose that state blindly. Revoke/reissue sensitive invitations after an incident restore.
8. Run `ANALYZE`, application smoke tests and reconciliation sample checks. Record elapsed time,
   errors, measured data-loss window and reviewer. Rehearse controlled cutover/rollback separately;
   a successful test restore does not authorize production replacement.

## Repository smoke evidence

`tests/database/test_run_backup.py` now creates a synthetic saved three-way run, source evidence,
findings and comment history, governance invitation/event, and a `7.25` inventory receipt. It proves
selected-run intelligence before capture, makes a PostgreSQL custom dump, restores into another empty
disposable database, and then verifies:

- exact Alembic revision `0008`, ENABLE/FORCE RLS on every application table, restricted runtime and
  identity roles, destructive-grant absence, immutable triggers, the dashboard activity index, and
  the inventory intelligence-window index;
- identity/membership/session authentication, invitation/governance evidence, source/report/audit and
  workflow evidence, and no tenant rows without an RLS context;
- a real re-login, the restored selected-run result state (6 matched, 11 review-required), and the
  restored `7.25` current inventory balance.

It requires `TEST_DATABASE_ADMIN_URL` plus compatible `pg_dump`/`pg_restore` on PATH (or test-only
`POSTGRES_BIN`) and explicitly skips without those clients. Phase 9 passed it locally with PostgreSQL
17.11 client/server. It does not test encryption, off-host transport, key recovery, large-data recovery
time, point-in-time recovery, or a production restore.

## Retention and deletion

Archive/restore and membership deactivation are visibility/access changes, not deletion. They retain
canonical source evidence, snapshots, findings, notes, invitations, and all event history. There is no permanent-purge endpoint, retention job,
or legal-hold workflow. Define those policies, including expired backup copies, before promising
data erasure. Keep test archives/logs out of Git. Dispose of approved expired copies using the
storage platform's reviewed recovery/retention policy, not broad filesystem deletion commands.
