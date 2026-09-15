import {
  ADMIN_API_PATH,
  ADMIN_PAGE_SIZE,
  MEMBERSHIP_ROLES,
} from "@/constants/admin";
import { AUTH_API_PATH } from "@/constants/auth";
import { apiFetch } from "@/lib/api/transport";
import type {
  AuditEntry,
  InvitationPreview,
  OrganizationInvitation,
  OrganizationMember,
  OrganizationSettings,
  Page,
} from "@/types/admin";
import type { MembershipRole } from "@/types/auth";

export class AdminRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AdminRequestError";
  }
}

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const timestamp = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const nullableTimestamp = (value: unknown) => value === null || timestamp(value);
const version = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const role = (value: unknown): value is MembershipRole =>
  text(value) && MEMBERSHIP_ROLES.includes(value as MembershipRole);

function invalid(): never {
  throw new AdminRequestError(
    0,
    "The administration response could not be read. Refresh to try again.",
  );
}

async function request(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(path, options);
  } catch {
    throw new AdminRequestError(
      0,
      "Unable to reach administration. Check your connection and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return invalid();
  }
  if (!response.ok) {
    const defaults: Record<number, string> = {
      401: "Your session expired. Sign in again.",
      403: "Organization administrator access is required.",
      404: "The requested organization resource was not found.",
      409: "This record changed. Refresh before trying again.",
      422: "Check the supplied fields.",
    };
    throw new AdminRequestError(
      response.status,
      object(payload) && text(payload.message)
        ? payload.message
        : (defaults[response.status] ?? "The request could not be completed."),
    );
  }
  return payload;
}

function json(method: "POST" | "PATCH", body: Record<string, unknown>): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function member(value: unknown): value is OrganizationMember {
  return (
    object(value) &&
    text(value.user_id) &&
    text(value.display_name) &&
    text(value.email) &&
    role(value.role) &&
    ["ACTIVE", "ARCHIVED"].includes(String(value.status)) &&
    version(value.version) &&
    timestamp(value.created_at)
  );
}

function invitation(value: unknown): value is OrganizationInvitation {
  return (
    object(value) &&
    text(value.id) &&
    text(value.email) &&
    role(value.role) &&
    ["PENDING", "ACCEPTED", "REVOKED"].includes(String(value.status)) &&
    typeof value.expired === "boolean" &&
    version(value.version) &&
    timestamp(value.created_at) &&
    timestamp(value.expires_at) &&
    nullableTimestamp(value.accepted_at) &&
    nullableTimestamp(value.revoked_at)
  );
}

function page<T>(value: unknown, guard: (item: unknown) => item is T): Page<T> {
  if (
    !object(value) ||
    !Array.isArray(value.items) ||
    value.items.length > ADMIN_PAGE_SIZE ||
    !value.items.every(guard) ||
    !(value.next_cursor === null || text(value.next_cursor))
  )
    return invalid();
  return value as unknown as Page<T>;
}

export async function getOrganization(): Promise<OrganizationSettings> {
  const value = await request(`${ADMIN_API_PATH}/organization`);
  if (!object(value) || !text(value.id) || !text(value.name) || !version(value.version))
    return invalid();
  return value as unknown as OrganizationSettings;
}

export async function renameOrganization(
  expectedVersion: number,
  name: string,
): Promise<OrganizationSettings> {
  const value = await request(
    `${ADMIN_API_PATH}/organization`,
    json("PATCH", { expected_version: expectedVersion, name }),
  );
  if (!object(value) || !text(value.id) || !text(value.name) || !version(value.version))
    return invalid();
  return value as unknown as OrganizationSettings;
}

function pagePath(resource: string, cursor?: string): string {
  const params = new URLSearchParams({ limit: String(ADMIN_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  return `${ADMIN_API_PATH}/${resource}?${params}`;
}

export async function getMembers(cursor?: string): Promise<Page<OrganizationMember>> {
  return page(await request(pagePath("members", cursor)), member);
}

export async function updateMember(
  member: OrganizationMember,
  changes: { role?: MembershipRole; status?: "ACTIVE" | "ARCHIVED" },
): Promise<Pick<OrganizationMember, "user_id" | "role" | "status" | "version">> {
  const value = await request(
    `${ADMIN_API_PATH}/members/${encodeURIComponent(member.user_id)}`,
    json("PATCH", { expected_version: member.version, ...changes }),
  );
  if (
    !object(value) ||
    !text(value.user_id) ||
    !role(value.role) ||
    !["ACTIVE", "ARCHIVED"].includes(String(value.status)) ||
    !version(value.version)
  )
    return invalid();
  return value as unknown as Pick<
    OrganizationMember,
    "user_id" | "role" | "status" | "version"
  >;
}

export async function getInvitations(
  cursor?: string,
): Promise<Page<OrganizationInvitation>> {
  return page(await request(pagePath("invitations", cursor)), invitation);
}

export async function createInvitation(
  email: string,
  invitedRole: MembershipRole,
): Promise<OrganizationInvitation> {
  const value = await request(
    `${ADMIN_API_PATH}/invitations`,
    json("POST", { email, role: invitedRole }),
  );
  return invitation(value) ? value : invalid();
}

export async function revokeInvitation(
  value: OrganizationInvitation,
): Promise<OrganizationInvitation> {
  const result = await request(
    `${ADMIN_API_PATH}/invitations/${encodeURIComponent(value.id)}/revoke`,
    json("POST", { expected_version: value.version }),
  );
  return invitation(result) ? result : invalid();
}

function auditEntry(value: unknown): value is AuditEntry {
  return (
    object(value) &&
    text(value.id) &&
    ["RUN", "WORKFLOW", "GOVERNANCE"].includes(String(value.source)) &&
    text(value.event_type) &&
    text(value.resource_type) &&
    text(value.resource_id) &&
    text(value.actor_user_id) &&
    text(value.actor_display_name) &&
    text(value.request_id) &&
    timestamp(value.created_at) &&
    object(value.metadata)
  );
}

export async function getAudit(cursor?: string): Promise<Page<AuditEntry>> {
  return page(await request(pagePath("audit", cursor)), auditEntry);
}

export async function previewInvitation(token: string): Promise<InvitationPreview> {
  const value = await request(
    `${AUTH_API_PATH}/invitations/preview`,
    json("POST", { token }),
  );
  if (
    !object(value) ||
    !text(value.organization_name) ||
    !text(value.email) ||
    !role(value.role) ||
    !timestamp(value.expires_at)
  )
    return invalid();
  return value as unknown as InvitationPreview;
}

export async function acceptInvitation(token: string): Promise<void> {
  await request(`${AUTH_API_PATH}/invitations/accept`, json("POST", { token }));
}

export async function registerInvited(
  token: string,
  displayName: string,
  password: string,
): Promise<void> {
  await request(
    `${AUTH_API_PATH}/register-invited`,
    json("POST", { token, display_name: displayName, password }),
  );
}
