const API_BASE_URL_ENV = "NEXT_PUBLIC_API_BASE_URL";
const REQUEST_TIMEOUT_ENV = "NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS";
const DEFAULT_REQUEST_TIMEOUT_MS = 120_000;

export function getApiBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!configuredUrl) {
    throw new Error(`${API_BASE_URL_ENV} is not configured`);
  }

  const url = new URL(configuredUrl);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`${API_BASE_URL_ENV} must use HTTP or HTTPS`);
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${API_BASE_URL_ENV} must contain only an origin`);
  }

  return url.origin;
}

export function getReconciliationTimeoutMs(): number {
  const configuredTimeout = process.env.NEXT_PUBLIC_RECONCILIATION_TIMEOUT_MS?.trim();
  if (!configuredTimeout) {
    return DEFAULT_REQUEST_TIMEOUT_MS;
  }
  if (!/^\d+$/.test(configuredTimeout)) {
    throw new Error(`${REQUEST_TIMEOUT_ENV} must be a positive integer`);
  }

  const timeoutMs = Number(configuredTimeout);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new Error(`${REQUEST_TIMEOUT_ENV} must be a positive integer`);
  }
  return timeoutMs;
}
