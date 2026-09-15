import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AdminShell } from "./admin-shell";
import { InvitationPage } from "./invitation-page";
import { MembersPage } from "./members-page";
import { SettingsPage } from "./settings-page";
import { AuthProvider } from "@/components/auth/auth-provider";
import {
  AdminRequestError,
  createInvitation,
  getInvitations,
  getMembers,
  getOrganization,
  previewInvitation,
  registerInvited,
  renameOrganization,
  revokeInvitation,
  updateMember,
} from "@/lib/api/admin";
import { authAction, getSession } from "@/lib/api/auth";
import type {
  OrganizationInvitation,
  OrganizationMember,
} from "@/types/admin";
import type { AuthSession } from "@/types/auth";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin",
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/lib/api/auth", () => ({ authAction: vi.fn(), getSession: vi.fn() }));
vi.mock("@/lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/admin")>();
  return {
    ...actual,
    createInvitation: vi.fn(),
    getInvitations: vi.fn(),
    getMembers: vi.fn(),
    getOrganization: vi.fn(),
    previewInvitation: vi.fn(),
    registerInvited: vi.fn(),
    renameOrganization: vi.fn(),
    revokeInvitation: vi.fn(),
    updateMember: vi.fn(),
  };
});

const member: OrganizationMember = {
  user_id: "user-a",
  display_name: '<img src=x onerror="window.xss=true">',
  email: "person@example.com",
  role: "MEMBER",
  status: "ACTIVE",
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
};
const invitation: OrganizationInvitation = {
  id: "invite-a",
  email: "invite@example.com",
  role: "MEMBER",
  status: "PENDING",
  expired: false,
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  expires_at: "2026-09-22T00:00:00Z",
  accepted_at: null,
  revoked_at: null,
};
const adminSession: AuthSession = {
  user: { id: "admin", email: "admin@example.com", display_name: "Admin" },
  memberships: [
    { organization_id: "org", organization_name: "Company", role: "ORG_ADMIN" },
  ],
  active_organization_id: "org",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMembers).mockResolvedValue({ items: [member], next_cursor: null });
  vi.mocked(getInvitations).mockResolvedValue({
    items: [invitation],
    next_cursor: null,
  });
  vi.mocked(getOrganization).mockResolvedValue({ id: "org", name: "Company", version: 1 });
  vi.mocked(getSession).mockResolvedValue(null);
  vi.mocked(authAction).mockResolvedValue(null);
  window.history.replaceState(null, "", "/");
});

it("renders untrusted member labels as text and performs versioned role changes", async () => {
  vi.mocked(updateMember).mockResolvedValue({
    user_id: member.user_id,
    role: "AP_MANAGER",
    status: "ACTIVE",
    version: 2,
  });
  const user = userEvent.setup();
  render(<MembersPage />);
  expect(await screen.findByText(member.display_name)).toBeVisible();
  expect(document.querySelector("img")).toBeNull();
  await user.selectOptions(screen.getByLabelText(`Role for ${member.display_name}`), "AP_MANAGER");
  expect(updateMember).toHaveBeenCalledWith(member, { role: "AP_MANAGER" });
});

it("focuses a conflict and requires an explicit refresh", async () => {
  vi.mocked(updateMember).mockRejectedValue(
    new AdminRequestError(409, "Membership changed. Refresh and try again."),
  );
  const user = userEvent.setup();
  render(<MembersPage />);
  await user.click(await screen.findByRole("button", { name: "Deactivate" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveFocus();
  expect(getMembers).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(getMembers).toHaveBeenCalledTimes(2));
});

it("creates and revokes invitations through explicit controls", async () => {
  vi.mocked(createInvitation).mockResolvedValue({
    ...invitation,
    id: "invite-b",
    email: "new@example.com",
  });
  vi.mocked(revokeInvitation).mockResolvedValue({
    ...invitation,
    status: "REVOKED",
    version: 2,
  });
  const user = userEvent.setup();
  render(<MembersPage />);
  await screen.findByRole("table", { name: "Organization invitations" });
  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.selectOptions(screen.getByLabelText("Role"), "AP_MANAGER");
  await user.click(screen.getByRole("button", { name: "Send invitation" }));
  expect(createInvitation).toHaveBeenCalledWith("new@example.com", "AP_MANAGER");
  await user.click(screen.getAllByRole("button", { name: "Revoke" }).at(-1)!);
  expect(revokeInvitation).toHaveBeenCalledWith(invitation);
});

it("renames the organization and states the actual retention boundary", async () => {
  vi.mocked(renameOrganization).mockResolvedValue({
    id: "org",
    name: "Renamed",
    version: 2,
  });
  const user = userEvent.setup();
  render(<SettingsPage />);
  const name = await screen.findByLabelText("Display name");
  await user.clear(name);
  await user.type(name, "Renamed");
  await user.click(screen.getByRole("button", { name: "Save name" }));
  expect(renameOrganization).toHaveBeenCalledWith(1, "Renamed");
  expect(screen.getByText(/no automatic retention or purge engine/i)).toBeVisible();
  expect(screen.getByText(/not a certification/i)).toBeVisible();
});

it("removes the invitation fragment and registers without client-selected email or role", async () => {
  window.history.replaceState(null, "", "/invite#token=private-token");
  vi.mocked(previewInvitation).mockResolvedValue({
    organization_name: "Invited Company",
    email: "invite@example.com",
    role: "AP_MANAGER",
    expires_at: "2026-09-22T00:00:00Z",
  });
  vi.mocked(registerInvited).mockResolvedValue();
  const user = userEvent.setup();
  render(
    <AuthProvider>
      <InvitationPage />
    </AuthProvider>,
  );
  expect(await screen.findByText("Invited Company")).toBeVisible();
  expect(window.location.hash).toBe("");
  await user.type(screen.getByLabelText("Your name"), "Invited Person");
  await user.type(screen.getByLabelText("Password"), "a long invited password");
  await user.click(screen.getByRole("button", { name: "Create invited account" }));
  expect(registerInvited).toHaveBeenCalledWith(
    "private-token",
    "Invited Person",
    "a long invited password",
  );
});

it("denies direct administration rendering for a non-admin membership", async () => {
  vi.mocked(getSession).mockResolvedValue({
    ...adminSession,
    memberships: [{ ...adminSession.memberships[0], role: "AP_MANAGER" }],
  });
  render(
    <AuthProvider>
      <AdminShell>
        <p>Private admin controls</p>
      </AdminShell>
    </AuthProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Admin access required" })).toBeVisible();
  expect(screen.queryByText("Private admin controls")).not.toBeInTheDocument();
});
