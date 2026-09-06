import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

Object.defineProperty(Element.prototype, "scrollIntoView", {
  configurable: true,
  value: vi.fn(),
});

Object.defineProperties(Element.prototype, {
  hasPointerCapture: {
    configurable: true,
    value: vi.fn(() => false),
  },
  releasePointerCapture: {
    configurable: true,
    value: vi.fn(),
  },
  setPointerCapture: {
    configurable: true,
    value: vi.fn(),
  },
});
