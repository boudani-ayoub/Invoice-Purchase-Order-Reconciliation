# Incident response runbook

## Use and ownership

This is a technical checklist, not a staffed incident service or a legal notification policy. Before
customer use, assign an incident commander, application owner, database owner, infrastructure owner,
communications owner, and evidence custodian with current contact paths. Define severity, escalation,
regulatory/contractual review, and decision authority for traffic isolation, credential rotation,
restoration, and customer communication.

For every suspected incident:

1. Record who detected it, UTC times, deployed commit/artifacts, migration revision, affected
   environment, first known request IDs/event classes, and current readiness. Do not copy payloads,
   tokens, credentials, or financial rows into tickets or chat.
2. Contain narrowly: remove public traffic, disable a compromised identity/provider credential, or
   isolate the database without destroying the evidence needed to establish scope.
3. Preserve access-controlled, checksummed copies of relevant sanitized application/proxy/system,
   PostgreSQL, SMTP-provider, deployment, and backup metadata. Record collection and access. Do not
   enable verbose body/parameter logging after the incident.
4. Rotate or revoke from a known-clean operator device. Treat credentials stored on the affected
   host as exposed. Confirm old access fails before declaring containment.
5. Recover into a verified state, rerun grant/RLS/trigger/revision checks, readiness, authenticated
   smoke, and scenario-specific checks. Observe before restoring normal traffic.
6. Communicate confirmed facts, affected period/scope, uncertainty, mitigations, and required user
   actions. Do not claim that data was untouched merely because no application error appeared.
7. Retain a timeline, decisions, evidence locations, follow-up owners, and a post-incident review.

## Scenario playbooks

### Suspected stolen session

- **Contain:** revoke the affected session through sign-out when available. With approved identity-DB
  operator access, revoke all live sessions for the user when theft scope is uncertain. Disable the
  membership/account if ongoing access cannot otherwise be contained.
- **Rotate/revoke:** a password reset transaction changes the password and revokes that user's
  sessions. Rotating `AUTH_CSRF_SECRET` alone does **not** revoke sessions; it only invalidates CSRF
  proofs. Do not rotate unrelated database/SMTP credentials without evidence.
- **Evidence:** preserve session creation/last-seen/revocation timestamps, membership/role changes,
  relevant request IDs, and append-only run/workflow/governance/inventory events. Never record the raw
  session token.
- **Recovery/communication:** confirm copied session material receives `401`, review tenant-scoped
  mutations, restore access with a new login, and tell the user which sessions/actions/time range are
  confirmed or still under review.

### Password compromise

- **Contain:** archive/disable the user or revoke sessions if active misuse is suspected. Protect the
  mailbox recovery path before relying on it.
- **Rotate/revoke:** complete the password-reset flow or a reviewed operator recovery; this revokes all
  existing sessions for that user. Invalidate outstanding reset/verification tokens as part of the
  account recovery decision.
- **Evidence:** preserve generic login/throttle outcomes and account/session timestamps, not attempted
  passwords. Check role, membership, and governance changes.
- **Recovery/communication:** verify a new password works, old sessions and password fail, mailbox
  control is restored, and affected tenant activity has been reviewed.

### CSRF secret compromise

- **Contain:** remove the compromised value and affected host/artifact from service. Confirm it did not
  enter frontend assets, logs, CI output, images, backups outside the approved boundary, or Git history.
- **Rotate/revoke:** generate a new random key in the secret manager and roll it coherently to every API
  worker. Existing CSRF proofs fail; users bootstrap new proofs. Separately revoke sessions if the event
  also exposed session cookies or server access.
- **Evidence:** retain secret-version/deployment access metadata without copying the value.
- **Recovery/communication:** verify old proofs fail, login/mutations work with fresh cookies, and state
  explicitly whether sessions were or were not revoked.

### Database credential compromise

- **Contain:** block the credential and public/database network path. Identify whether migration owner,
  backup operator, tenant runtime, or identity runtime was exposed; they have different blast radii.
- **Rotate/revoke:** rotate that login and passfile/secret independently, terminate its sessions, and
  redeploy consumers. If owner/admin access was exposed, treat schema, functions, RLS, triggers, grants,
  roles, and data as potentially altered.
- **Evidence:** preserve connection/audit/network/deployment metadata and a protected logical/physical
  recovery point. Avoid database parameter logging that can copy row values.
- **Recovery/communication:** compare schema/revision/owners/grants/policies/triggers to reviewed code,
  run tenant-isolation and immutable-ledger tests, and use correct-forward or isolated restoration as
  approved. Scope communication by accessible role, not only observed queries.

### SMTP credential compromise

- **Contain:** revoke the provider credential and suspend outbound authentication mail when messages
  cannot be trusted. Keep login/session service available only if the recovery limitation is explicit.
- **Rotate/revoke:** issue a least-privilege provider credential and update the private environment.
  Revoke/reissue sensitive pending invitations or email tokens when provider logs or mailbox delivery
  may have exposed links.
- **Evidence:** preserve provider event IDs, recipients/times/statuses, DNS/authentication state, and
  application delivery-failure classes without message bodies or fragment tokens.
- **Recovery/communication:** send a synthetic verification/recovery/invitation through the approved
  provider, confirm TLS/certificate validation and sender controls, and explain delayed/reissued links.

### Invitation, reset, or verification token exposure

- **Contain:** never paste the token or fragment URL into evidence systems. Remove published artifacts
  where possible and determine token purpose, account/invitation, expiry, and consumption state by
  hash-backed records.
- **Rotate/revoke:** tokens are single-use and hash-only. Issue a replacement, which consumes the prior
  active token for that purpose; revoke a pending invitation before reissuing. If a reset was consumed,
  treat the account and sessions as compromised.
- **Evidence:** preserve token record identifiers/timestamps/status and governance events, not raw values.
- **Recovery/communication:** prove the old value fails, the new flow works once, and any resulting
  membership/session was reviewed.

### Accidental public database exposure

- **Contain:** remove the public route/security-group/listener immediately while preserving provider
  flow/access logs. Do not assume strong passwords make exposure acceptable.
- **Rotate/revoke:** rotate every reachable database credential and relevant CA/client credential;
  terminate sessions. If owner access was reachable, follow the owner-compromise path above.
- **Evidence:** preserve network exposure start/end, source/destination telemetry, PostgreSQL connection
  logs, role activity, schema/security snapshots, and backup state.
- **Recovery/communication:** prove private-only reachability, `verify-full` transport, role separation,
  RLS/grants/triggers, and tenant-isolation tests. Scope potential access by privileges and exposure
  window even when query evidence is incomplete.

### Suspicious tenant-access event

- **Contain:** revoke the actor's session/membership and, if needed, drain traffic while distinguishing
  an authorization failure from a confirmed crossover. Preserve the append-only event trail.
- **Rotate/revoke:** rotate user credentials when compromised; rotate service/database credentials only
  when the trust boundary indicates it. Do not repair rows before evidence capture.
- **Evidence:** correlate request UUID, normalized route, actor, organization, role changes, RLS context,
  and audit/workflow/governance/inventory events. Avoid copying notes or financial bodies.
- **Recovery/communication:** reproduce with synthetic tenants, verify live role downgrade/inactivation,
  cross-tenant `404` behavior, RLS/composite FKs, and aggregate isolation. Report confirmed affected
  organizations and uncertainty, not a blanket “no breach” based on one layer.

### Corrupted migration or release

- **Contain:** stop promotion and writes when further mutation can increase damage. Record exact commit,
  artifacts, revision, migration output, readiness, and smoke failures.
- **Rotate/revoke:** credentials usually do not need rotation unless exposed. Never automatically run
  `alembic downgrade`.
- **Evidence:** preserve pre/post schema, row counts, grants/RLS/triggers, query errors, backup reference,
  and change timeline.
- **Recovery/communication:** follow the [rollback decision](deployment.md#rollback-runbook): keep the
  schema only when prior-app compatibility is proven; otherwise correct-forward or restore/cut over
  after isolated verification and data-loss review.

### Backup theft or unauthorized access

- **Contain:** revoke storage/operator access, stop replication/distribution, and preserve object access
  and key-management logs. A compressed PostgreSQL dump is not encrypted by default.
- **Rotate/revoke:** rotate exposed storage, encryption, database, and backup-operator credentials as
  indicated. Assume the backup includes password hashes, token/session hashes, identity, financial
  evidence, notes, governance history, and inventory ledger.
- **Evidence:** record exact backup, encryption/key state, recipients, accesses, and retention copies
  without restoring it into an untrusted environment.
- **Recovery/communication:** validate remaining protected copies and key recovery, perform a clean
  restore rehearsal, and scope notification to the data and time represented by the copy.

### Backup restore event

- **Contain:** restore only into an empty isolated target with outgoing mail and customer traffic off.
  Preserve the source backup and original environment until the cutover decision is reviewed.
- **Rotate/revoke:** decide whether restored sessions, recovery tokens, and pending invitations must be
  revoked; old auth state can become valid again. Use new environment/service credentials.
- **Evidence:** record backup provenance/checksum, revision, versions, row-count/security verification,
  measured data-loss window, errors, reviewers, and cutover decision.
- **Recovery/communication:** complete the [backup/restore runbook](backup-restore.md), authenticated
  smoke, readiness, grant/RLS/trigger verification, and post-cutover observation. State the measured
  recovery window; do not claim a guaranteed RPO/RTO.

## Closure criteria

An incident is not closed merely because `/health/ready` is green. The incident commander must have
documented containment, credential/session/token disposition, affected scope and uncertainty,
evidence custody, restored technical controls, business-path smoke, monitoring period, communications,
and assigned corrective actions. Review the [final threat model](threat-model-final.md) after material
architecture or trust-boundary changes.
