import {
  AUTH_API_PATH,
  AUTH_EXPIRED_EVENT,
  CSRF_HEADER,
} from "@/constants/auth";
import { getApiBaseUrl } from "@/lib/config";

let csrf: string | null = null;

export function clearCsrf(): void {
  csrf = null;
}

export function rememberCsrf(payload: unknown): void {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "csrf_token" in payload &&
    typeof payload.csrf_token === "string"
  ) {
    csrf = payload.csrf_token;
  }
}

async function bootstrap(signal?: AbortSignal | null): Promise<string> {
  if (!csrf) {
    const response = await fetch(`${getApiBaseUrl()}${AUTH_API_PATH}/csrf`, {
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!response.ok) throw new Error("Unable to initialize a secure request.");
    const payload: unknown = await response.json();
    rememberCsrf(payload);
    if (!csrf) throw new Error("Invalid security response.");
  }
  return csrf;
}

export async function apiFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(options.headers);
  if (
    options.method &&
    !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())
  ) {
    headers.set(CSRF_HEADER, await bootstrap(options.signal));
  }
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (response.status === 401) {
    clearCsrf();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  } else if (response.status === 403) {
    clearCsrf();
  }
  return response;
}
