import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./transport";
import {
  acceptInvitation,
  createInvitation,
  getAudit,
  getMembers,
  previewInvitation,
  renameOrganization,
  revokeInvitation,
  updateMember,
} from "./admin";
import type {
  AuditEntry,
  OrganizationInvitation,
  OrganizationMember,
} from "@/types/admin";

vi.mock("./transport", () => ({ apiFetch: vi.fn() }));

const member: OrganizationMember = {
  user_id: "user-a",
  display_name: "<img src=x onerror=alert(1)>",
  email: "person@example.com",
  role: "MEMBER",
  status: "ACTIVE",
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
};
const invitation: OrganizationInvitation = {
  id: "invite-a",
  email: "invite@example.com",
  role: "AP_MANAGER",
  status: "PENDING",
  expired: false,
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  expires_at: "2026-09-22T00:00:00Z",
  accepted_at: null,
  revoked_at: null,
};
const audit: AuditEntry = {
  id: "event-a",
  source: "GOVERNANCE",
  event_type: "INVITATION_CREATED",
  resource_type: "INVITATION",
  resource_id: "invite-a",
  actor_user_id: "user-a",
  actor_display_name: "Administrator",
  request_id: "request-a",
  created_at: "2026-09-15T00:00:00Z",
  metadata: { email: "invite@example.com" },
};

beforeEach(() => vi.mocked(apiFetch).mockReset());

it("uses bounded member keyset reads and versioned member changes", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [member], next_cursor: "next" }),
  );
  expect(await getMembers()).toEqual({ items: [member], next_cursor: "next" });
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/admin/members?limit=25",
    {},
  );
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...member, role: "AP_MANAGER", version: 2 }),
  );
  await updateMember(member, { role: "AP_MANAGER" });
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/admin/members/user-a",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ expected_version: 1, role: "AP_MANAGER" }),
    }),
  );
});

it("keeps invitation tokens in POST bodies and out of request URLs", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({
      organization_name: "Company",
      email: "invite@example.com",
      role: "MEMBER",
      expires_at: "2026-09-22T00:00:00Z",
    }),
  );
  await previewInvitation("private-token");
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/auth/invitations/preview",
    expect.objectContaining({ body: JSON.stringify({ token: "private-token" }) }),
  );
  expect(vi.mocked(apiFetch).mock.calls.at(-1)?.[0]).not.toContain("private-token");
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json({ accepted: true }));
  await acceptInvitation("private-token");
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/auth/invitations/accept",
    expect.objectContaining({ method: "POST" }),
  );
});

it("uses versions for rename and revoke without automatic retries", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ id: "org", name: "Changed", version: 2 }),
  );
  await renameOrganization(1, "Changed");
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/admin/organization",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ expected_version: 1, name: "Changed" }),
    }),
  );
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...invitation, status: "REVOKED", version: 2 }),
  );
  await revokeInvitation(invitation);
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/api/v1/admin/invitations/invite-a/revoke",
    expect.objectContaining({ body: JSON.stringify({ expected_version: 1 }) }),
  );
});

it("validates audit events and invitation responses", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [audit], next_cursor: null }),
  );
  expect((await getAudit()).items).toEqual([audit]);
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json(invitation));
  expect(await createInvitation(invitation.email, invitation.role)).toEqual(invitation);
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ ...invitation, version: 0 }),
  );
  await expect(createInvitation(invitation.email, invitation.role)).rejects.toMatchObject({
    status: 0,
  });
});

it("rejects unbounded pages and malformed timestamps", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: Array(26).fill(member), next_cursor: null }),
  );
  await expect(getMembers()).rejects.toMatchObject({ status: 0 });
  vi.mocked(apiFetch).mockResolvedValueOnce(
    Response.json({ items: [{ ...member, created_at: "not-a-time" }], next_cursor: null }),
  );
  await expect(getMembers()).rejects.toMatchObject({ status: 0 });
});

for (const status of [401, 403, 404, 409, 422, 500]) {
  it(`surfaces a safe ${status} error once`, async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json({ message: "Safe server message" }, { status }),
    );
    await expect(getMembers()).rejects.toMatchObject({ status });
    expect(apiFetch).toHaveBeenCalledOnce();
  });
}
