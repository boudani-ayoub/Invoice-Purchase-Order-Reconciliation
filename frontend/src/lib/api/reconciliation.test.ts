import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ReconciliationRequestError,
  reconcileFiles,
} from "@/lib/api/reconciliation";
import { RECONCILIATION_REPORT_FIXTURE } from "@/test/fixtures/reconciliation";
import type { UploadFiles } from "@/constants/uploads";

const fetchMock = vi.fn<typeof fetch>();

function uploadFiles(): UploadFiles {
  return {
    purchase_orders: new File(["purchase orders"], "purchase_orders.csv"),
    receipts: new File(["receipts"], "goods_receipts.csv"),
    invoices: new File(["invoices"], "invoices.csv"),
  };
}

function jsonResponse(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
  vi.stubGlobal("fetch", fetchMock);
});

describe("reconcileFiles", () => {
  it("posts exactly the three backend multipart fields", async () => {
    fetchMock.mockResolvedValue(jsonResponse(RECONCILIATION_REPORT_FIXTURE, 200));

    await expect(reconcileFiles(uploadFiles())).resolves.toEqual(RECONCILIATION_REPORT_FIXTURE);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/v1/reconcile");
    expect(request?.method).toBe("POST");
    expect(request?.headers).toBeUndefined();
    expect(request?.body).toBeInstanceOf(FormData);
    expect([...((request?.body as FormData).keys())]).toEqual([
      "purchase_orders",
      "receipts",
      "invoices",
    ]);
  });

  it("maps structured CSV validation errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: "validation_error",
          message: "Uploaded CSV data failed validation.",
          issues: [
            {
              file: "purchase_orders",
              source: "purchase_orders.csv",
              row: 2,
              column: "ordered_quantity",
              value: "-3",
              reason: "ordered_quantity must be greater than zero",
            },
          ],
        },
        422,
      ),
    );

    await expect(reconcileFiles(uploadFiles())).rejects.toMatchObject({
      detail: {
        kind: "validation",
        issues: [{ row: 2, column: "ordered_quantity", value: "-3" }],
      },
    });
  });

  it("maps file-size errors without losing the backend limit", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: "file_too_large", file: "invoices", max_bytes: 10 * 1024 * 1024 },
        413,
      ),
    );

    await expect(reconcileFiles(uploadFiles())).rejects.toMatchObject({
      detail: { kind: "file_too_large", file: "invoices", maxBytes: 10 * 1024 * 1024 },
    });
  });

  it("maps FastAPI missing-field validation", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            {
              type: "missing",
              loc: ["body", "receipts"],
              msg: "Field required",
              input: null,
            },
          ],
        },
        422,
      ),
    );

    await expect(reconcileFiles(uploadFiles())).rejects.toMatchObject({
      detail: { kind: "missing_upload", fields: ["receipts"] },
    });
  });

  it("maps server and network failures to safe error categories", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: "internal_error", message: "Internal server error." }, 500),
    );
    await expect(reconcileFiles(uploadFiles())).rejects.toMatchObject({
      detail: { kind: "server" },
    });

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch internal detail"));
    await expect(reconcileFiles(uploadFiles())).rejects.toEqual(
      new ReconciliationRequestError({ kind: "network" }),
    );
  });

  it("rejects a successful response that does not match the typed contract", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ summary: {}, results: [] }, 200));

    await expect(reconcileFiles(uploadFiles())).rejects.toMatchObject({
      detail: { kind: "unexpected_response" },
    });
  });
});
