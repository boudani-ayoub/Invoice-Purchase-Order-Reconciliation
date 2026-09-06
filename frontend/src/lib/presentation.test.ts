import { describe, expect, it } from "vitest";

import { getIssuePresentation } from "@/constants/issues";
import { formatDecimalString, formatFileSize } from "@/lib/formatters";

describe("presentation helpers", () => {
  it("formats decimal strings without floating-point conversion", () => {
    expect(formatDecimalString("12345678901234567890.123456789")).toBe(
      "12,345,678,901,234,567,890.123456789",
    );
  });

  it("keeps unknown future issue codes visible", () => {
    expect(getIssuePresentation("SOME_NEW_CODE")).toMatchObject({
      label: "Some New Code",
      tone: "warning",
    });
  });

  it("formats transport file sizes consistently", () => {
    expect(formatFileSize(10 * 1024 * 1024)).toBe("10.0 MB");
  });
});
