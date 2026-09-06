function configuredPort(name: string, fallback: number): number {
  const value = process.env[name]?.trim();
  if (!value) {
    return fallback;
  }

  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be a valid TCP port`);
  }
  return port;
}

export const E2E_API_HOST = process.env.E2E_API_HOST?.trim() || "127.0.0.1";
export const E2E_WEB_HOST = process.env.E2E_WEB_HOST?.trim() || "127.0.0.1";
export const E2E_API_PORT = configuredPort("E2E_API_PORT", 8010);
export const E2E_WEB_PORT = configuredPort("E2E_WEB_PORT", 3010);
export const E2E_API_ORIGIN = `http://${E2E_API_HOST}:${E2E_API_PORT}`;
export const E2E_WEB_ORIGIN = `http://${E2E_WEB_HOST}:${E2E_WEB_PORT}`;
