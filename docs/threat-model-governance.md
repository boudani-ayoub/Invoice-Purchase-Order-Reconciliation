# Organization governance threat model

## Scope and trust boundaries

Product Phase 6 covers administration of one active organization: display-name changes,
membership roles and ACTIVE/ARCHIVED state, email invitations, invited registration, and a merged
read-only activity timeline. It is not platform administration and does not manage credentials,
sessions, user email, billing, payment approval, inventory, permanent deletion, or retention.

The browser is untrusted. UI role checks improve navigation only. FastAPI authenticates the opaque
session, derives organization and actor from it, checks an explicit permission, then the governance
service re-reads the active organization and membership through `reconcile_identity`. Tenant run and
workflow events remain behind `reconcile_runtime` and forced tenant RLS. The identity role has no
procurement access; runtime has no invitation, governance-event, credential, session, or membership
mutation access. The migration owner and PostgreSQL administrator remain stronger trust boundaries.

## Permission matrix

Permissions are explicit immutable sets. A new enum value is granted to no role until deliberately
added and tested.

| Capability | MEMBER | AP_MANAGER | ORG_ADMIN |
| --- | :---: | :---: | :---: |
| Run analyses; view run and finding workflow | Yes | Yes | Yes |
| Comment and transition an assigned finding | Yes | Yes | Yes |
| Update/archive runs; manage any finding; view dashboard | No | Yes | Yes |
| View organization administration | No | No | Yes |
| Rename organization | No | No | Yes |
| Change membership role/status | No | No | Yes |
| Create/revoke invitations | No | No | Yes |
| View organization audit | No | No | Yes |

Current membership is checked again for every operation. A downgrade or deactivation therefore
affects the next request without trusting a role stored in browser state. It cannot retroactively
cancel an already-authorized transaction.

## State and concurrency controls

Membership records are never hard-deleted. ACTIVE and ARCHIVED are access states; the role remains
part of history. Organizations, memberships, and invitations use positive versions. Every update
checks `expected_version` under a lock and returns `409` on stale state; clients refresh explicitly
and do not retry mutations automatically.

Every membership mutation locks the organization row before selecting the target. That shared
serialization point makes the last-active-ORG_ADMIN check safe across different target membership
rows: a demotion or deactivation is rejected unless another active administrator exists. The
mutation and its one or more governance events commit or roll back together.

## Invitation security decision

Invitation tokens contain 256 random bits. Only a SHA-256 hash is stored. The raw token appears in
the emailed `/invite#token=...` fragment, not a query string, API response, database plaintext,
application log, or audit metadata. The landing page reads the fragment into memory and immediately
removes it from browser history before preview. The app has no analytics or third-party scripts.

Possession of a valid invitation delivered to the invited mailbox is accepted as proof of control
for new-user registration. On success, the server derives email, organization, and role from the
locked invitation, marks the email verified, creates User/Credential/Membership, accepts the
invitation, and appends governance in one identity transaction. It creates no private organization.
An existing user must authenticate with the same normalized email. Expired, revoked, used, random,
and concurrently consumed tokens fail; only one concurrent acceptance can commit.

The existing mail service sends plain text through certificate-verified SMTP. Delivery happens
after the durable invitation transaction. A failure logs only a generic operational message; it
does not expose token, address, or provider exception. There is no durable mail queue or resend
endpoint: an administrator must revoke and reissue. Provider/mailbox compromise, forwarded links,
endpoint compromise, browser extensions, and same-origin XSS can still expose a usable token.

An administrator receives specific errors only for same-organization membership or pending-invite
conflicts. The endpoint never reports whether an address has an account elsewhere, so it is not a
global user-search or account-enumeration API.

## Audit design

`governance_events` is append-only through SELECT/INSERT-only identity grants and an UPDATE/DELETE
rejection trigger. Events carry server-derived organization, actor, request UUID, typed resource,
timestamp, and bounded JSON details. Raw tokens, credentials, workflow comment bodies, and
resolution-note bodies are excluded. Run and workflow event protections remain unchanged.

`GET /api/v1/admin/audit` fetches at most `limit + 1` rows from each run, workflow, and governance
source, performs a deterministic `(created_at, source rank, id)` merge, and returns at most the
requested 1–100 rows with an opaque keyset cursor. Actor labels are fetched only through a
same-organization membership join; missing historical labels render as `Former member`. The UI
renders labels and IDs as text and intentionally does not render event metadata.

The three sources are read in two restricted database transactions, so the merged page is not a
single cross-database snapshot. New events may appear between requests; the cursor prevents an
unbounded read but is not a cryptographic sequence or non-repudiation mechanism. A database owner
can alter schema/triggers or records.

## Threat review

| Threat | Implemented mitigation | Residual risk / limit | Evidence |
| --- | --- | --- | --- |
| AP_MANAGER receives admin access | Five admin permissions are granted only to explicit ORG_ADMIN set; server checks each route | Future permissions can be misclassified | Permission-map regression and UI/API denial E2E |
| Last-admin race | Organization row serializes all membership mutations before invariant check | Database owner or out-of-band writer can bypass service behavior | Single and concurrent demotion/deactivation tests |
| Membership or invitation IDOR | Server-derived organization predicate; other-tenant IDs return `404`; forced identity RLS | Identity-login compromise can choose identity context | Two-tenant route and direct-policy tests |
| Stale session/role | Session plus active user/organization/membership and permission rechecked on every operation | In-flight authorized work is not revoked retroactively | Live promotion, downgrade, deactivate/reactivate tests |
| Invitation leakage | High entropy, hash-only DB, fragment URL, cleanup, no response/log/audit token | Mailbox/provider/device/XSS compromise can capture token | Hash/log/audit inspection and browser fragment check |
| Invitation replay/race | Row lock, PENDING/expiry check, single accepted transition | Captured token works until expiry/revocation/acceptance | Reuse, expiry, revoke, and concurrent acceptance tests |
| Email mismatch or client role injection | Existing account email must match; invited registration derives email/org/role server-side; extra fields forbidden | Mail forwarding is indistinguishable from intended mailbox use for a new account | Mismatch, no-new-org, invited-role, mass-assignment tests |
| Account enumeration | No global directory/search; errors expose only same-organization member/pending state to admin | A malicious admin already knows its own organization roster | Existing-account-outside-org and duplicate tests |
| CSRF | Trusted Origin plus session/context-bound proof on every write and invitation preview | Trusted-origin XSS can obtain a proof | Missing/invalid proof route tests |
| Actor/tenant injection | Request bodies forbid extra fields; actor, organization, request ID come from server context | Full application compromise exceeds this boundary | Server-context event assertions |
| Stored XSS / unsafe mail | React text rendering; plain-text mail; markup payloads retained as text | Future HTML mail or metadata UI needs escaping review | Markup member/browser test and static review |
| Audit leakage | ORG_ADMIN only, tenant filters/RLS, same-org labels, workflow bodies excluded | Event types and resource IDs are still sensitive metadata | Cross-tenant audit and body-exclusion tests |
| Event loss or mutation | Governance write/event atomic; append-only grants and trigger | Owner/admin can alter history; merged sources are not one snapshot | Forced insertion failure rollback and direct UPDATE/DELETE denial |
| Unbounded reads | Member, invitation, and audit pages default 25, cap 100, use keysets | Large retained tables still need monitoring and capacity tests | Cursor/limit validation and bounded-merge tests |
| Runtime privilege widening | Runtime gets no new identity-table privileges; identity updates are column-limited | Identity service compromise is highly privileged by design | Migration grant matrix and direct denied access |

## Data governance and operational exclusions

Raw upload bytes remain temporary. Validated source records, immutable result snapshots, workflow
comments/resolution notes, run audit, workflow events, governance events, memberships, and
invitation history are persisted. Archive and membership deactivation are reversible hiding/access
changes, not deletion. Backups may retain all of this after live-state changes.

There is no automatic retention or purge engine, permanent organization/member deletion, legal
hold, secure-destruction guarantee, audit clearing, tamper-evident export, MFA, SSO, or platform
administrator. Real SMTP, production proxy/TLS, provider logging, abuse/load limits, recovery,
monitoring, incident response, and retention execution require deployment-specific verification.
This assessment is not a production-readiness statement or GDPR, SOC 2, or other compliance claim.
