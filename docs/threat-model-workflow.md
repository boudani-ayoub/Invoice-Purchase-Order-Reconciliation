# Finding workflow threat model

## Scope and assets

Phase 4 overlays operational state on immutable saved findings. Assets are tenant isolation,
source/report integrity, current assignment/status/schedule, persistent comments and resolution
notes, and actor-aware event history. Financial engine decisions and authoritative monetary
summaries remain in the original stored report. A resolved finding is not a payment approval,
waiver, source correction, or legal determination.

Trust boundaries remain browser → authenticated API → separated identity/tenant database roles.
Migration owner/administrator access is privileged and never used by HTTP. The member directory
is the only new identity read: verified organization, narrow projections, bounded pages or bounded
assignee IDs from already scoped findings. It exposes no email, credentials, session, or recovery data.

## Reviewed threats

| Threat | Control and verification | Residual boundary |
| --- | --- | --- |
| Finding/event IDOR | Fresh authorization, explicit organization predicates, forced RLS; foreign/missing detail/mutation/event/run-filter IDs return 404 | Authorization-denied roles receive 403 before resource disclosure |
| RLS bypass or missing context | ENABLE/FORCE RLS, transaction-local bound context, tests of known own/foreign events and missing context | Arbitrary runtime SQL can set its own tenant context; prevent application compromise |
| Assignee user-ID injection | UUID input, active same-org membership/account lookup, composite membership FK | Memberships may become inactive after assignment; current check is not a distributed revocation protocol |
| Cross-tenant member enumeration | Verified active organization bound in every directory query; narrow ID/name/role picker; UUID keyset pagination | Authorized members may see their organization's active member names |
| Identity/runtime privilege expansion | No identity grants added; runtime still cannot SELECT users/credentials/sessions; identity cannot read findings/events | Identity service remains trusted to scope its already privileged reads |
| Stale or revoked access | Existing session/user/org/membership checks plus reauthentication/live role check after finding lock waits | Revocation racing after the final check retains the existing in-flight request boundary |
| Member privilege escalation | Central permission map; locked finding assignee must equal member actor; direct API denial tests | UI visibility is convenience only |
| Mass assignment | Extra fields forbidden; separate manager patch, transition, comment schemas; state field allow-list | Privileged runtime SQL can mutate granted workflow columns outside API contracts |
| CSRF / cross-origin mutation | Existing signed session-bound proof and trusted Origin on all POST/PATCH routes; 16 KiB JSON ceiling | Proxy limits and HTTPS topology still require deployment verification |
| Lost updates | SELECT FOR UPDATE, post-lock authorization, version comparison, 409, one winner in concurrent-connection tests | No automatic merge; a stale editor must refresh |
| Partial state/history write | Finding changes and workflow events flush and commit in one tenant transaction; injected failures roll back | No distributed side effects or outbound delivery are attempted |
| Event tampering | Same-org actor/finding FKs, SELECT/INSERT only, UPDATE/DELETE trigger including ordinary owner/admin row mutation | Owner/superuser can change DDL; not a cryptographic ledger |
| Snapshot/evidence mutation | Column-scoped finding UPDATE; immutable source grants/snapshot trigger unchanged; complete source/snapshot text comparisons | Backup administrators and schema owners remain trusted |
| Stored XSS | React text rendering for source/member/run/comment/resolution text; no HTML injection; browser and unit XSS cases | Exported or externally copied text must still be treated as untrusted |
| SQL/cursor injection | Strict UUID/enum/bool inputs, bounded decoded timestamp/UUID cursors, bound SQL values | Queue performance needs measurement at deployment scale |
| Oversize/invalid workflow content | 4000 Unicode-character limit; nonblank trimmed text; NUL/surrogate/extra-field rejection; DB message/metadata constraints; JSON body limit | No content moderation or semantic verification of investigation statements |
| Clock and reminder confusion | Explicit timezone input, UTC normalization, finite calendar bounds, deterministic server-clock flags; resolved findings suppress due flags | Dates can become due between reads; refresh is explicit, not proactive delivery |
| Comment/note leakage | Error-class/request-ID-only API logs; note/comment body omitted from error responses and event metadata | PostgreSQL error DETAIL, proxy capture, backups, and browser traces require restricted logging/retention |
| Duplicate actions after uncertain responses | No automatic mutation retry; UI asks for finding/timeline refresh after network ambiguity; no-op state patches rejected | Comments have no idempotency key; deliberate resubmission creates another append-only comment |
| Unbounded workflow growth | Text/body/metadata/page bounds, keyset queue/history, relevant indexes | Per-tenant quotas, authenticated mutation rate budgets, retention and purge remain deployment/governance work |
| False finance or notification claims | UI and docs define resolution as investigation closure; reminders in-app only; no monetary aggregation | Users must not treat workflow status as accounting authorization |

## Operational requirements

Treat comments/resolution notes as retained business information. Archive hides a run from active
History but does not delete findings, events, source evidence, or backups. Include all 22 tables
in protected logical backups. Migration 0004 deliberately refuses downgrade to avoid erasing
workflow history; recovery requires a reviewed backup/restore plan.

The synthetic workflow seeder is imported only by the disposable test launcher and has no HTTP
endpoint. It creates random test credentials supplied privately by Playwright, not shipped accounts.
Never deploy the test launcher or expose `E2E_WORKFLOW_SEED` via public environment variables.

No Phase 5 dashboard, payment approval, legal/penalty logic, member administration, outbound
reminder delivery, queue, purge, MFA, or SSO is introduced. This review is not certification or
production-readiness approval. See [persistence threats](threat-model-persistence.md),
[deployment](deployment.md), and [security roadmap](security-roadmap.md).
