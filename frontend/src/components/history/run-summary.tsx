import type { RunListItem } from "@/types/runs";

export function RunSummary({ run }: { run: RunListItem }) {
  const summary = run.summary;
  return (
    <p className="text-sm text-muted-foreground">
      {"invoice_lines_processed" in summary
        ? `${summary.invoice_lines_processed} invoice lines · ${summary.matched_lines} matched · ${summary.review_required_lines} review required`
        : `${summary.po_lines_processed} order lines · ${summary.receipt_lines_processed} receipt lines · ${summary.orphan_receipt_lines} unresolved receipts`}
    </p>
  );
}

export function RunDate({ value }: { value: string }) {
  return (
    <time dateTime={value}>
      {new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))}
    </time>
  );
}
