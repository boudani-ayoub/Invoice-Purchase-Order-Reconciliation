import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ANALYSIS_MODES, analysisApiPath } from "@/constants/analysis-modes";
import { analyzeFiles, isAnalysisReport } from "./analyses";
import { ANALYSIS_REPORTS, INVOICE_PO_REPORT } from "@/test/fixtures/analyses";
import type { UploadFiles } from "@/constants/uploads";

beforeEach(() =>
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test"),
);
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
for (const report of ANALYSIS_REPORTS) {
  it(`validates and posts the ${report.mode} contract with only required files`, async () => {
    expect(isAnalysisReport(report)).toBe(true);
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(report)));
    vi.stubGlobal("fetch", fetchMock);
    const files: UploadFiles = {
      purchase_orders: new File(["po"], "po.csv"),
      receipts: new File(["receipt"], "receipt.csv"),
      invoices: new File(["invoice"], "invoice.csv"),
    };
    expect(await analyzeFiles(report.mode, files)).toEqual(report);
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toContain(analysisApiPath(report.mode));
    expect([...request.body.keys()]).toEqual(
      ANALYSIS_MODES[report.mode].requiredSources,
    );
  });
}
it("rejects a valid report for a different requested mode", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(INVOICE_PO_REPORT))),
  );
  await expect(
    analyzeFiles("invoice-receipt", {
      purchase_orders: null,
      receipts: new File(["r"], "r.csv"),
      invoices: new File(["i"], "i.csv"),
    }),
  ).rejects.toMatchObject({ detail: { kind: "unexpected_response" } });
});
it("rejects incomplete mode-specific records", () => {
  expect(
    isAnalysisReport({
      ...INVOICE_PO_REPORT,
      results: [{ status: "MATCHED" }],
    }),
  ).toBe(false);
  expect(isAnalysisReport({ ...INVOICE_PO_REPORT, mode: "other" })).toBe(false);
});
