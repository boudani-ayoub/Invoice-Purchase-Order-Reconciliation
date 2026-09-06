const API_BASE_URL_ENV = "NEXT_PUBLIC_API_BASE_URL";

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
