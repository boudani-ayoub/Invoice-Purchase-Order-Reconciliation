import { AUTH_API_PATH, AUTH_TIMEOUT_MS } from "@/constants/auth";
import { apiFetch, rememberCsrf } from "@/lib/api/transport";
import type { AuthAction, AuthSession, Membership } from "@/types/auth";

export class AuthRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AuthRequestError";
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function membership(value: unknown): value is Membership {
  return (
    object(value) &&
    typeof value.organization_id === "string" &&
    typeof value.organization_name === "string" &&
    ["MEMBER", "AP_MANAGER", "ORG_ADMIN"].includes(String(value.role))
  );
}

function session(value: unknown): value is AuthSession {
  return (
    object(value) &&
    object(value.user) &&
    typeof value.user.id === "string" &&
    typeof value.user.email === "string" &&
    typeof value.user.display_name === "string" &&
    Array.isArray(value.memberships) &&
    value.memberships.every(membership) &&
    (value.active_organization_id === null ||
      typeof value.active_organization_id === "string")
  );
}

async function request(
  path: string,
  body?: Record<string, string>,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);
  try {
    const response = await apiFetch(`${AUTH_API_PATH}/${path}`, {
      method: body ? "POST" : "GET",
      body: body ? JSON.stringify(body) : undefined,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      signal: controller.signal,
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      throw new AuthRequestError(
        response.status,
        object(payload) && typeof payload.message === "string"
          ? payload.message
          : "The request could not be completed.",
      );
    }
    rememberCsrf(payload);
    return payload;
  } catch (error) {
    if (error instanceof AuthRequestError) throw error;
    throw new AuthRequestError(
      0,
      controller.signal.aborted
        ? "The request timed out. Try again."
        : "Unable to reach the service. Check your connection and try again.",
    );
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getSession(): Promise<AuthSession | null> {
  try {
    const payload = await request("me");
    if (!session(payload))
      throw new AuthRequestError(0, "The session response could not be read.");
    return payload;
  } catch (error) {
    if (error instanceof AuthRequestError && error.status === 401) return null;
    throw error;
  }
}

export async function authAction(
  action: AuthAction,
  body: Record<string, string> = {},
): Promise<string | null> {
  const payload = await request(action, body);
  return object(payload) && typeof payload.message === "string"
    ? payload.message
    : null;
}
