import type { UploadField } from "@/constants/uploads";
import type { AnalysisMode, FulfillmentStatus } from "@/types/analysis";

export const ANALYSIS_HUB_PATH = "/reconcile";
export const analysisPath = (mode: AnalysisMode) =>
  `${ANALYSIS_HUB_PATH}/${mode}`;
export const analysisApiPath = (mode: AnalysisMode) =>
  `/api/v1/analyses/${mode}`;

export interface AnalysisModeDefinition {
  id: AnalysisMode;
  title: string;
  question: string;
  description: string;
  requiredSources: readonly UploadField[];
  controls: string;
  limitations: string;
  resultTitle: string;
  submitLabel: string;
}

export const ANALYSIS_MODES: Record<AnalysisMode, AnalysisModeDefinition> = {
  "invoice-po": {
    id: "invoice-po",
    title: "Invoice vs Purchase Order",
    question: "Does the supplier's invoice agree with what you ordered?",
    description:
      "Classic two-way invoice match for billed quantity, price, supplier, and order limits.",
    requiredSources: ["purchase_orders", "invoices"],
    controls:
      "PO and item references, duplicates, supplier, currency, cumulative ordered capacity, and price tolerance.",
    limitations:
      "Receipt coverage is not checked. A match does not confirm delivery.",
    resultTitle: "Invoice vs Purchase Order results",
    submitLabel: "Run invoice match",
  },
  "invoice-receipt": {
    id: "invoice-receipt",
    title: "Invoice vs Goods Receipt",
    question: "Are the billed quantities supported by recorded receipts?",
    description:
      "Receipt-coverage invoice check using shared PO line and item references.",
    requiredSources: ["receipts", "invoices"],
    controls:
      "Exact PO/line/item receipt references, duplicate invoices, and cumulative receipt coverage.",
    limitations:
      "PO price, ordered quantity, supplier, currency, and commercial terms are not verified. Exposure uses the invoice's own price; it is not a PO price variance. Duplicate groups carry full exposure, counted once in totals.",
    resultTitle: "Receipt coverage results",
    submitLabel: "Check receipt coverage",
  },
  "po-receipt": {
    id: "po-receipt",
    title: "Purchase Order vs Goods Receipt",
    question: "What did you order, and what has actually been received?",
    description:
      "Receiving and fulfillment analysis for deliveries, open quantities, and unexpected receipts.",
    requiredSources: ["purchase_orders", "receipts"],
    controls:
      "Aggregated receipts, outstanding delivery, over-receipt, and unresolved PO/line/item references.",
    limitations:
      "Invoices and payment exposure are not checked. Partial and missing deliveries can be open orders. Receipt quantities are not inventory balances.",
    resultTitle: "Receiving and fulfillment results",
    submitLabel: "Analyze fulfillment",
  },
  "three-way": {
    id: "three-way",
    title: "Three-way Match",
    question: "Does the invoice agree with both the order and the receipts?",
    description:
      "Compare invoices with ordered terms and received quantities. Most complete set of current invoice controls.",
    requiredSources: ["purchase_orders", "receipts", "invoices"],
    controls:
      "PO/item references, duplicates, supplier, currency, price tolerance, and cumulative PO and receipt capacity.",
    limitations:
      "Results reflect the uploaded exports. Taxes, returns, credit notes, and as-of-date controls are not included.",
    resultTitle: "Reconciliation results",
    submitLabel: "Run reconciliation",
  },
};

export const FULFILLMENT_LABELS: Record<FulfillmentStatus, string> = {
  FULLY_RECEIVED: "Fully received",
  PARTIALLY_RECEIVED: "Partially received",
  NOT_RECEIVED: "Not received",
  OVER_RECEIVED: "Over-received",
};
