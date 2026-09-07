import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthForm } from "./auth-form";
import { AuthProvider } from "./auth-provider";
import { ProtectedApp } from "./protected-app";
import { AUTH_EXPIRED_EVENT } from "@/constants/auth";
import { authAction, getSession } from "@/lib/api/auth";
import type { AuthSession } from "@/types/auth";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/api/auth", () => ({ authAction: vi.fn(), getSession: vi.fn() }));

const SESSION: AuthSession = {
  user: {
    id: "user",
    email: "person@example.com",
    display_name: "Test person",
  },
  memberships: [
    {
      organization_id: "org-a",
      organization_name: "Company A",
      role: "ORG_ADMIN",
    },
  ],
  active_organization_id: "org-a",
};

beforeEach(() => {
  vi.mocked(getSession).mockReset().mockResolvedValue(null);
  vi.mocked(authAction).mockReset().mockResolvedValue(null);
  replace.mockReset();
  window.history.replaceState(null, "", "/");
});

function form(kind: Parameters<typeof AuthForm>[0]["kind"]) {
  render(
    <AuthProvider>
      <AuthForm kind={kind} />
    </AuthProvider>,
  );
}

function protectedPage() {
  render(
    <AuthProvider>
      <ProtectedApp>
        <h1>Analysis workspace</h1>
      </ProtectedApp>
    </AuthProvider>,
  );
}

it("submits only the required registration fields with password guidance", async () => {
  const user = userEvent.setup();
  form("register");
  await user.type(screen.getByLabelText("Your name"), "Person");
  await user.type(screen.getByLabelText("Organization name"), "Company");
  await user.type(screen.getByLabelText("Email"), "person@example.com");
  await user.type(
    screen.getByLabelText("Password", { exact: true }),
    "a long private passphrase",
  );
  await user.click(screen.getByRole("button", { name: "Show password" }));
  expect(screen.getByLabelText("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(authAction).toHaveBeenCalledWith("register", {
    display_name: "Person",
    organization_name: "Company",
    email: "person@example.com",
    password: "a long private passphrase",
  });
  expect(await screen.findByRole("status")).toHaveFocus();
});

it("shows and focuses a readable invalid-login error", async () => {
  vi.mocked(authAction).mockRejectedValue(
    new Error("Unable to sign in with these credentials."),
  );
  const user = userEvent.setup();
  form("login");
  await user.type(screen.getByLabelText("Email"), "person@example.com");
  await user.type(screen.getByLabelText("Password", { exact: true }), "wrong");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to sign in",
  );
  expect(screen.getByRole("alert")).toHaveFocus();
});

it("refreshes the session after successful login", async () => {
  const user = userEvent.setup();
  form("login");
  await user.type(screen.getByLabelText("Email"), "person@example.com");
  await user.type(
    screen.getByLabelText("Password", { exact: true }),
    "a long private passphrase",
  );
  vi.mocked(getSession).mockResolvedValue(SESSION);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/reconcile"));
  expect(getSession).toHaveBeenCalledTimes(2);
});

it("redirects unauthenticated protected pages", async () => {
  protectedPage();
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText("Analysis workspace")).not.toBeInTheDocument();
});

it("shows the current organization and logs out", async () => {
  vi.mocked(getSession).mockResolvedValue(SESSION);
  const user = userEvent.setup();
  protectedPage();
  expect(await screen.findByText("Company A")).toBeVisible();
  expect(screen.getByText("Test person")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  expect(authAction).toHaveBeenCalledWith("logout");
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});

it("requires and submits explicit organization selection", async () => {
  const multiple: AuthSession = {
    ...SESSION,
    active_organization_id: null,
    memberships: [
      ...SESSION.memberships,
      {
        organization_id: "org-b",
        organization_name: "Company B",
        role: "MEMBER",
      },
    ],
  };
  vi.mocked(getSession)
    .mockResolvedValueOnce(multiple)
    .mockResolvedValue({ ...multiple, active_organization_id: "org-b" });
  const user = userEvent.setup();
  protectedPage();
  await user.selectOptions(
    await screen.findByLabelText("Organization"),
    "org-b",
  );
  expect(authAction).toHaveBeenCalledWith("select-organization", {
    organization_id: "org-b",
  });
  expect(await screen.findByText("Analysis workspace")).toBeVisible();
});

it("keeps a session network failure distinct from anonymous state", async () => {
  vi.mocked(getSession).mockRejectedValue(new Error("offline"));
  protectedPage();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to check your session",
  );
  expect(replace).not.toHaveBeenCalled();
});

it("removes protected content after session expiration", async () => {
  vi.mocked(getSession).mockResolvedValue(SESSION);
  protectedPage();
  await screen.findByText("Analysis workspace");
  act(() => window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT)));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText("Analysis workspace")).not.toBeInTheDocument();
});

it("consumes verification tokens from memory after clearing the URL", async () => {
  window.history.replaceState(null, "", "/verify-email#token=secret-link");
  const user = userEvent.setup();
  form("verify");
  expect(window.location.hash).toBe("");
  await user.click(screen.getByRole("button", { name: "Verify email" }));
  expect(authAction).toHaveBeenCalledWith("verify-email", {
    token: "secret-link",
  });
});

it("requests recovery without exposing account existence", async () => {
  vi.mocked(authAction).mockResolvedValue(
    "If eligible, recovery instructions have been sent.",
  );
  const user = userEvent.setup();
  form("forgot");
  await user.type(screen.getByLabelText("Email"), "person@example.com");
  await user.click(
    screen.getByRole("button", { name: "Send recovery instructions" }),
  );
  expect(authAction).toHaveBeenCalledWith("forgot-password", {
    email: "person@example.com",
  });
  expect(await screen.findByRole("status")).toHaveTextContent("If eligible");
});
