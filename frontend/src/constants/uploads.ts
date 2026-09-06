export const UPLOAD_SOURCES = [
  {
    field: "purchase_orders",
    label: "Purchase orders",
    actionLabel: "Choose purchase orders",
    description: "What was ordered, including supplier, item, quantity, and agreed price.",
  },
  {
    field: "receipts",
    label: "Goods receipts",
    actionLabel: "Choose goods receipts",
    description: "What was received against each purchase order line.",
  },
  {
    field: "invoices",
    label: "Invoices",
    actionLabel: "Choose invoices",
    description: "What suppliers are requesting to be paid.",
  },
] as const;

export type UploadField = (typeof UPLOAD_SOURCES)[number]["field"];
export type UploadFiles = Record<UploadField, File | null>;

export const EMPTY_UPLOADS: UploadFiles = {
  purchase_orders: null,
  receipts: null,
  invoices: null,
};

export const UPLOAD_FIELD_LABELS: Record<UploadField, string> = Object.fromEntries(
  UPLOAD_SOURCES.map((source) => [source.field, source.label]),
) as Record<UploadField, string>;
