import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { Page, TestInfo } from "@playwright/test";

const SAMPLE_DIR = path.resolve(process.cwd(), "../examples/sample_data");
const MEBIBYTE = 1024 * 1024;
const APP_UPLOAD_LIMIT_BYTES = 10 * MEBIBYTE;
const LARGE_ALLOWED_TARGET_BYTES = 9 * MEBIBYTE;

export interface SourceFiles {
  purchase_orders: string;
  receipts: string;
  invoices: string;
}

export const SAMPLE_FILES: SourceFiles = {
  purchase_orders: path.join(SAMPLE_DIR, "purchase_orders.csv"),
  receipts: path.join(SAMPLE_DIR, "goods_receipts.csv"),
  invoices: path.join(SAMPLE_DIR, "invoices.csv"),
};

const INPUT_LABELS: Record<keyof SourceFiles, string> = {
  purchase_orders: "Choose purchase orders",
  receipts: "Choose goods receipts",
  invoices: "Choose invoices",
};

export async function selectSourceFiles(
  page: Page,
  overrides: Partial<SourceFiles> = {},
): Promise<void> {
  const files = { ...SAMPLE_FILES, ...overrides };
  for (const field of Object.keys(files) as Array<keyof SourceFiles>) {
    await page.getByLabel(INPUT_LABELS[field]).setInputFiles(files[field]);
  }
}

async function outputFile(testInfo: TestInfo, filename: string): Promise<string> {
  const destination = testInfo.outputPath(filename);
  await mkdir(path.dirname(destination), { recursive: true });
  return destination;
}

export async function createInvalidPurchaseOrders(testInfo: TestInfo): Promise<string> {
  const destination = await outputFile(testInfo, "invalid-purchase-orders.csv");
  await writeFile(
    destination,
    [
      "po_number,line_number,supplier_id,order_date,currency,item_code,description,ordered_quantity,unit_price",
      "PO-E2E,1,SUP-E2E,2026-01-05,MAD,ITEM-E2E,Invalid quantity,-3,25.50",
      "",
    ].join("\n"),
    "utf8",
  );
  return destination;
}

export async function createLargeAllowedPurchaseOrders(testInfo: TestInfo): Promise<string> {
  const destination = await outputFile(testInfo, "large-allowed-purchase-orders.csv");
  let content = await readFile(SAMPLE_FILES.purchase_orders, "utf8");
  const description = "A".repeat(100_000);
  let row = 1;

  while (Buffer.byteLength(content, "utf8") < LARGE_ALLOWED_TARGET_BYTES) {
    content += `PO-E2E-${row},1,SUP-E2E-${row},2026-02-01,MAD,ITEM-E2E-${row},${description},1,1.00\n`;
    row += 1;
  }
  if (Buffer.byteLength(content, "utf8") >= APP_UPLOAD_LIMIT_BYTES) {
    throw new Error("Generated near-limit fixture exceeded the application upload limit");
  }

  await writeFile(destination, content, "utf8");
  return destination;
}

export async function createOversizedPurchaseOrders(testInfo: TestInfo): Promise<string> {
  const destination = await outputFile(testInfo, "oversized-purchase-orders.csv");
  await writeFile(destination, Buffer.alloc(APP_UPLOAD_LIMIT_BYTES + 1, "x"));
  return destination;
}

export async function createUnicodeSources(
  testInfo: TestInfo,
): Promise<{ files: SourceFiles; identifiers: string[] }> {
  const supplier = `SUP-مورد-東京-${"S".repeat(72)}`;
  const purchaseOrder = `PO-東京-${"P".repeat(84)}`;
  const item = `ITEM-قطعة-${"I".repeat(80)}`;
  const invoice = `INV-فاتورة-${"N".repeat(80)}`;
  const receipt = `REC-受領-${"R".repeat(80)}`;
  const purchaseOrders = await outputFile(testInfo, "unicode-purchase-orders.csv");
  const receipts = await outputFile(testInfo, "unicode-goods-receipts.csv");
  const invoices = await outputFile(testInfo, "unicode-invoices.csv");

  await Promise.all([
    writeFile(
      purchaseOrders,
      [
        "po_number,line_number,supplier_id,order_date,currency,item_code,description,ordered_quantity,unit_price",
        `${purchaseOrder},1,${supplier},2026-03-01,MAD,${item},Support écran,2,50.00`,
        "",
      ].join("\n"),
      "utf8",
    ),
    writeFile(
      receipts,
      [
        "receipt_id,line_number,po_number,po_line_number,receipt_date,item_code,received_quantity",
        `${receipt},1,${purchaseOrder},1,2026-03-02,${item},2`,
        "",
      ].join("\n"),
      "utf8",
    ),
    writeFile(
      invoices,
      [
        "invoice_number,line_number,supplier_id,invoice_date,po_number,po_line_number,currency,item_code,invoiced_quantity,unit_price",
        `${invoice},1,${supplier},2026-03-03,${purchaseOrder},1,MAD,${item},2,50.00`,
        "",
      ].join("\n"),
      "utf8",
    ),
  ]);

  return {
    files: { purchase_orders: purchaseOrders, receipts, invoices },
    identifiers: [supplier, purchaseOrder, item, invoice],
  };
}
