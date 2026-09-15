# Product Phase 6 — Organization administration and governance

## Outcome and scope

Phase 6 adds organization-scoped administration without creating a platform-admin role. An active
ORG_ADMIN can view members, change membership roles and access state, create/revoke email
invitations, rename the organization display name, and inspect a bounded activity timeline. A
valid invitation supports both an existing account and a new invited account without creating an
unrelated personal organization.

The reconciliation engine, saved report truth, immutable source evidence, workflow state machine,
dashboard metric definitions, Decimal policy, CLI contract, and stateless API behavior are
unchanged. The phase does not add permanent deletion, retention execution, payment approval,
inventory, billing, platform administration, MFA/SSO, background jobs, or a new mail library.

## Starting point and decisions

- Original verified remote Phase 5 HEAD: `0b95ecae64b4191e2904d862851dfc34e4bf7bf8`.
- Phase 5 GitHub Actions: [push run 34921520243](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/34921520243), with Python 3.11, Python 3.12, PostgreSQL/authentication, and frontend/browser jobs successful on that SHA.
- Phase 5 CI documentation correction: `6fa230a594c250633de7394d79f7b61247459578`.
- Exact Phase 6 implementation baseline: `6fa230a594c250633de7394d79f7b61247459578`.
- The unrelated root `package-lock.json` remains unchanged and untracked. SHA-256: `DAA0308A5EB8C96651E80918807B4EC840C32FA960BC4308AC915136161868AE`.

The prompt's open contracts were resolved before implementation:

1. Replace the AP_MANAGER wildcard permission map before adding admin privileges. All role sets are
   explicit, and newly introduced permissions default to no access.
2. Keep organization administration in the existing restricted identity domain. The tenant
   runtime cannot update memberships or access invitations/governance events.
3. Retain memberships and model deactivation as ARCHIVED. Serialize every member mutation on the
   organization row so concurrent changes to different rows cannot remove the last active admin.
4. Use expected versions for organizations, memberships, and invitations. A stale request returns
   `409`; the UI offers Refresh and never silently retries a mutation.
5. Reject a second pending invitation for the same organization/normalized email until the first
   is revoked. Do not expose account existence outside that organization.
6. Treat possession of the high-entropy mailed invitation as email control for invited
   registration. Email, organization, and role come only from the invitation; the email is marked
   verified and no new organization is created.
7. Keep run, workflow, and governance events in their existing security domains. Read at most
   `limit + 1` per source and merge deterministically rather than weakening old foreign keys or
   loading all history.
8. State the actual retention boundary. Archive/deactivation are not deletion; no purge engine,
   legal hold, secure destruction, or compliance certification is claimed.

## Authorization matrix

| Capability | MEMBER | AP_MANAGER | ORG_ADMIN |
| --- | :---: | :---: | :---: |
| Run analysis; view History and Work | Yes | Yes | Yes |
| Comment/transition assigned finding | Yes | Yes | Yes |
| Edit/archive runs; manage findings; dashboard | No | Yes | Yes |
| Open organization administration | No | No | Yes |
| Rename organization | No | No | Yes |
| Change member role/status | No | No | Yes |
| Create/revoke invitations | No | No | Yes |
| View organization audit | No | No | Yes |

Every administration route authenticates the session and then rechecks the active organization,
membership state, current role, and exact permission. Client-supplied organization/actor/request
identities are forbidden. Cross-tenant resource IDs return `404`; insufficient roles return `403`.

## Database and service design

Migration `0006_organization_governance` adds:

- positive version 1 columns on organizations and organization_memberships;
- `organization_invitations` with normalized email, intended role, 32-byte token hash,
  PENDING/ACCEPTED/REVOKED lifecycle, creator/acceptor attribution, expiry, and history indexes;
- a partial unique constraint for one pending organization/email invitation;
- append-only `governance_events` with typed events/resources, server request ID, actor, timestamp,
  and bounded JSON details;
- forced identity RLS, column-level identity updates, and no runtime access to the two new tables.

Existing Phase 1–5 rows, policies, grants, source evidence, result snapshots, run audit, and finding
events survive clean and `0005` upgrades. Downgrade is allowed only before Phase 6 state has been
used; otherwise it raises rather than silently erasing governance history or version changes.

Member mutation follows one transaction:

```text
authenticate current session
→ require exact admin permission
→ lock active organization
→ re-read active membership and role
→ load same-organization target
→ check expected version
→ enforce another active admin when necessary
→ update role/status and version
→ append governance event(s)
→ commit
```

Invitation tokens have 256 random bits. Only SHA-256 hashes are stored. Links use
`/invite#token=...`; no API response, database plaintext, log message, or audit metadata contains
the raw token. Preview reveals only organization display name, invited email/role, and expiry to
the token holder. Acceptance locks and consumes the invitation once. Mail uses the existing
plain-text SMTP abstraction after the durable invitation commit; failed delivery logs a generic
message and requires revoke/reissue because there is no durable mail queue.

The general audit view merges run `audit_events`, workflow `finding_events`, and identity
`governance_events` by `(created_at, source rank, id)` with an opaque keyset cursor. Each source is
queried with `limit + 1`; the returned page defaults to 25 and caps at 100. Actor labels are joined
only through membership in the active organization. Workflow comment and resolution bodies are
not projected, and the admin UI does not render event metadata. The two database-role reads are
not a single cross-database snapshot.

## API and frontend map

| Method and route | Permission / contract |
| --- | --- |
| `GET /api/v1/admin/organization` | ORG_ADMIN view; server-selected active organization |
| `PATCH /api/v1/admin/organization` | name + expected_version; atomic rename event |
| `GET /api/v1/admin/members` | bounded keyset organization directory |
| `PATCH /api/v1/admin/members/{user_id}` | explicit role/status + expected_version |
| `GET /api/v1/admin/invitations` | bounded keyset invitation history |
| `POST /api/v1/admin/invitations` | normalized email + MEMBER/AP_MANAGER/ORG_ADMIN role |
| `POST /api/v1/admin/invitations/{id}/revoke` | pending only + expected_version |
| `GET /api/v1/admin/audit` | bounded merged run/workflow/governance timeline |
| `POST /api/v1/auth/invitations/preview` | valid token; minimal invitation projection |
| `POST /api/v1/auth/invitations/accept` | matching authenticated email |
| `POST /api/v1/auth/register-invited` | token + display name + password; invitation owns scope/role |

All writes and invitation preview require the existing trusted-Origin, session/context-bound CSRF
proof. Pydantic models forbid extra fields. The frontend adds `/admin`, `/admin/members`,
`/admin/settings`, `/admin/audit`, and `/invite`; all untrusted labels render as React text. The
settings page explains temporary raw uploads, retained validated records/snapshots/workflow/audit,
archive semantics, backups, and the absence of purge/compliance controls.

## Verification

Final verification used PostgreSQL 17.11, Python 3.11.16 and 3.12.7, Node 24, Next.js 16.3.4, and
Chromium against real FastAPI and restricted database roles. Test accounts and databases were
synthetic and disposable; no production service or customer data was used.

| Check | Result |
| --- | --- |
| Python 3.11 complete suite | 707 passed in 224.13s; no skips; one existing Starlette/AnyIO deprecation warning |
| Python 3.12 complete suite | 707 passed in 224.69s; no skips; same warning |
| Python 3.12 split check | 334 non-database + 373 database tests passed |
| Focused governance and upgrade | 16 passed; includes clean/0005 upgrade, policies and grants |
| Ruff | Lint passed; format check passed |
| pip check | No broken requirements on Python 3.11 or 3.12 |
| Frontend unit/component suite | 146 passed across 15 files |
| ESLint | Passed |
| Next production build | Passed; 21 routes generated, including all admin and invite routes |
| Chromium complete suite | 37 passed in 1.9m with no retries |
| axe | 33 tested-state scans; zero serious or critical violations |
| npm audit --audit-level=high | 0 vulnerabilities |

Database tests cover explicit role grants, live downgrade/deactivation, tenant IDOR, membership and
invitation concurrency, last-admin safety, version conflicts, normalized email, pending duplicate,
hash-only token storage, no token logging/audit, expiry/revoke/replay, email mismatch, existing-user
acceptance, invited registration with no new organization, server-owned role/scope/actor, event
atomicity/immutability, bounded audit merge/body exclusion, and runtime/identity separation.

Browser tests exercise the real admin page, safe markup rendering, invite creation, member
promotion and dashboard gain, downgrade and access loss, deactivation/reactivation, another
organization's isolation, last-admin rejection, two-admin stale edit, invited registration,
persistent rename, newly invited member visibility, audit events, keyboard tables, 375 px layout,
and AP_MANAGER denial in both UI and all four admin GET resources.

## Review findings and residual risks

- The first end-to-end failure was an ambiguous test selector because the invited email correctly
  appeared in both member and invitation tables. The assertion now scopes to the member table.
- The final formatter gate found two non-semantic line-wrap differences in the migration downgrade
  and an older upgrade test. They were formatted and recorded in a separate commit before docs.
- Local Playwright-owned API teardown can hang on Windows. Local configuration now reuses an
  explicitly running server when present; CI still owns isolated servers. The focused and full
  suites exited normally under that supported local path.
- Next reports workspace-root ambiguity because of the pre-existing root lockfile. It was not
  edited, removed, or staged. Playwright also reports existing `NO_COLOR`/`FORCE_COLOR` precedence.
- SMTP/provider delivery, proxy/TLS behavior, penetration/load testing, monitoring, retention
  execution, and disaster recovery were not verified as production services.
- A captured invitation works until expiry, revocation, or acceptance. Mailbox/provider/device,
  browser-extension, and trusted-origin compromise remain outside token secrecy guarantees.
- An identity-login compromise is highly privileged by design; a database owner can alter schema,
  RLS, triggers, or history. The merged audit is not cryptographic non-repudiation.
- Authorization changes do not cancel a request already authorized and holding its transaction.
- Audit sources are read in separate restricted transactions, so a page is not a globally atomic
  snapshot. Retained tables still require deployment-specific capacity and retention controls.

This phase does not claim production readiness, GDPR/SOC 2 compliance, legal-hold support, or
secure destruction.

## Local handoff

| Commit | Purpose |
| --- | --- |
| `6fa230a594c250633de7394d79f7b61247459578` | Phase 5 CI correction and exact Phase 6 baseline |
| `f747d1cf1d6a6cc4a9cbe3952c192a271f51bfd0` | Replace implicit AP manager permissions with explicit role grants |
| `cd457206ca59e1897377aebb8ae31fa2ccabe3b9` | Identity schema, governance service, admin/auth API, security and database tests |
| `be3c87282d5839aac21502536bff6180d17f2407` | Administration/invitation UI, typed client, frontend tests, and real-service browser coverage |
| `8f4e45fafe9447124ed9af89f6731f8a2f46dc11` | Apply the final Ruff formatting corrections |

The concluding commit is `docs: record product phase 6 architecture`; its SHA is reported in the
completion message rather than embedded self-referentially here. The final working tree should have
no tracked changes and only the pre-existing untracked root lockfile.

Relative to the exact implementation baseline, Phase 6 changes 50 files: 9 backend modules, 1
migration, 5 Python test files, 20 frontend files, 1 browser-seed script, and 14 documentation or
configuration files.

No push was performed. Phase 6 is the stopping point. Phase 7 inventory foundation and explicit
stock movements is next and was not implemented.
