export type IssueTone = "warning" | "destructive";

interface IssuePresentation {
  label: string;
  description: string;
  tone: IssueTone;
}

const ISSUE_PRESENTATION: Record<string, IssuePresentation> = {
  UNKNOWN_PO: {
    label: "Unknown purchase order",
    description: "The referenced purchase order was not found.",
    tone: "destructive",
  },
  UNKNOWN_ITEM: {
    label: "Unknown item",
    description: "The invoiced item does not match the referenced order line.",
    tone: "destructive",
  },
  DUPLICATE_INVOICE: {
    label: "Duplicate invoice",
    description: "The same invoice identity appears more than once.",
    tone: "destructive",
  },
  SUPPLIER_MISMATCH: {
    label: "Supplier mismatch",
    description: "The invoice supplier differs from the purchase order supplier.",
    tone: "destructive",
  },
  CURRENCY_MISMATCH: {
    label: "Currency mismatch",
    description: "The invoice and purchase order use different currencies.",
    tone: "destructive",
  },
  MISSING_RECEIPT: {
    label: "Missing receipt",
    description: "No received quantity supports this invoice line.",
    tone: "warning",
  },
  QUANTITY_EXCEEDS_PO: {
    label: "Quantity exceeds PO",
    description: "Cumulative invoiced quantity exceeds the ordered quantity.",
    tone: "warning",
  },
  QUANTITY_EXCEEDS_RECEIPT: {
    label: "Quantity exceeds receipt",
    description: "Cumulative invoiced quantity exceeds the received quantity.",
    tone: "warning",
  },
  PRICE_MISMATCH: {
    label: "Price mismatch",
    description: "The invoice unit price differs from the purchase order price.",
    tone: "warning",
  },
};

export const STATUS_PRESENTATION = {
  MATCHED: {
    label: "Matched",
    className: "border-success/25 bg-success-muted text-success",
  },
  REVIEW_REQUIRED: {
    label: "Review required",
    className: "border-warning/30 bg-warning-muted text-warning-foreground",
  },
} as const;

export function getIssuePresentation(code: string): IssuePresentation {
  return (
    ISSUE_PRESENTATION[code] ?? {
      label: humanizeIssueCode(code),
      description: "The service returned an issue that requires review.",
      tone: "warning",
    }
  );
}

export function humanizeIssueCode(code: string): string {
  return code
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
}
