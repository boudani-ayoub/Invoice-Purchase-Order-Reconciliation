import { CircleCheck, Files, ListChecks, TriangleAlert } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { ReconciliationSummary as Summary } from "@/types/reconciliation";

interface ReconciliationSummaryProps {
  summary: Pick<
    Summary,
    | "invoices_processed"
    | "invoice_lines_processed"
    | "matched_lines"
    | "review_required_lines"
  >;
}

export function ReconciliationSummary({ summary }: ReconciliationSummaryProps) {
  const metrics = [
    {
      label: "Invoices processed",
      value: summary.invoices_processed,
      icon: Files,
      tone: "text-primary",
    },
    {
      label: "Invoice lines",
      value: summary.invoice_lines_processed,
      icon: ListChecks,
      tone: "text-primary",
    },
    {
      label: "Matched",
      value: summary.matched_lines,
      icon: CircleCheck,
      tone: "text-success",
    },
    {
      label: "Review required",
      value: summary.review_required_lines,
      icon: TriangleAlert,
      tone: "text-warning-foreground",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map(({ label, value, icon: Icon, tone }) => (
        <Card key={label} size="sm" className="shadow-none">
          <CardContent className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">{label}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {value}
              </p>
            </div>
            <Icon aria-hidden="true" className={`size-5 ${tone}`} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
