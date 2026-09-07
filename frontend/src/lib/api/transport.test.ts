import { beforeEach, expect, it, vi } from "vitest";
import { AUTH_EXPIRED_EVENT, CSRF_HEADER } from "@/constants/auth";
import { apiFetch, clearCsrf, rememberCsrf } from "./transport";

const fetchMock = vi.fn<typeof fetch>();
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

beforeEach(() => {
  fetchMock.mockReset();
  clearCsrf();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
  vi.stubGlobal("fetch", fetchMock);
});

it("bootstraps pre-auth CSRF and sends cookies centrally", async () => {
  fetchMock
    .mockResolvedValueOnce(json({ csrf_token: "proof" }))
    .mockResolvedValueOnce(json({}));
  await apiFetch("/api/v1/auth/login", { method: "POST", body: "{}" });
  expect(fetchMock.mock.calls[0][0]).toBe(
    "https://api.example.test/api/v1/auth/csrf",
  );
  for (const [, options] of fetchMock.mock.calls) {
    expect(options?.credentials).toBe("include");
    expect(options?.cache).toBe("no-store");
  }
  expect(
    new Headers(fetchMock.mock.calls[1][1]?.headers).get(CSRF_HEADER),
  ).toBe("proof");
});

it("uses rotated CSRF without persisting browser credentials", async () => {
  rememberCsrf({ csrf_token: "rotated" });
  fetchMock.mockResolvedValue(json({}));
  const local = vi.spyOn(Storage.prototype, "setItem");
  await apiFetch("/api/v1/reconcile", { method: "POST", body: new FormData() });
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(
    new Headers(fetchMock.mock.calls[0][1]?.headers).get(CSRF_HEADER),
  ).toBe("rotated");
  expect(local).not.toHaveBeenCalled();
  local.mockRestore();
});

it("clears stale CSRF for an explicit retry without replaying a POST", async () => {
  rememberCsrf({ csrf_token: "stale" });
  fetchMock.mockResolvedValueOnce(json({}, 403));
  expect((await apiFetch("/api/v1/reconcile", { method: "POST" })).status).toBe(
    403,
  );
  expect(fetchMock).toHaveBeenCalledOnce();
  fetchMock
    .mockResolvedValueOnce(json({ csrf_token: "fresh" }))
    .mockResolvedValueOnce(json({}));
  await apiFetch("/api/v1/reconcile", { method: "POST" });
  expect(
    new Headers(fetchMock.mock.calls[2][1]?.headers).get(CSRF_HEADER),
  ).toBe("fresh");
});

it("notifies the app when the session expires", async () => {
  const expired = vi.fn();
  window.addEventListener(AUTH_EXPIRED_EVENT, expired);
  fetchMock.mockResolvedValue(json({}, 401));
  await apiFetch("/api/v1/auth/me");
  expect(expired).toHaveBeenCalledOnce();
  window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
});

it("does not submit credentials when CSRF bootstrap fails", async () => {
  fetchMock.mockRejectedValue(new TypeError("offline"));
  await expect(
    apiFetch("/api/v1/auth/login", { method: "POST" }),
  ).rejects.toThrow();
  expect(fetchMock).toHaveBeenCalledOnce();
});
