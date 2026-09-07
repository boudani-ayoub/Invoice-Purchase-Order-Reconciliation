export const AUTH_API_PATH = "/api/v1/auth";
export const AUTH_ROUTES = {
  login: "/login",
  register: "/register",
  forgot: "/forgot-password",
  reset: "/reset-password",
  verify: "/verify-email",
} as const;
export const AUTH_EXPIRED_EVENT = "reconcile:session-expired";
export const CSRF_HEADER = "X-CSRF-Token";
export const PASSWORD_MIN_LENGTH = 15;
export const PASSWORD_MAX_LENGTH = 128;
export const AUTH_TIMEOUT_MS = 15000;
