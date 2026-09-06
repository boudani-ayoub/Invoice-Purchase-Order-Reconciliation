import type { AnalysisReport } from "@/types/analysis";
import { FulfillmentResults } from "./fulfillment-results";
import { ReconciliationSummary } from "./reconciliation-summary";
import { IssueOverview } from "./issue-overview";
import { DisputedAmounts } from "./disputed-amounts";
import { ResultsTable } from "./results-table";

export function AnalysisResults({ report }: { report: AnalysisReport }) {
  if (report.mode === "po-receipt")
    return <FulfillmentResults report={report} />;
  return (
    <>
      <ReconciliationSummary summary={report.summary} />
      <p className="text-sm text-muted-foreground">
        Matched means the line passed the controls listed for this analysis.
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        <IssueOverview issueCounts={report.summary.issue_counts} />
        {report.mode === "invoice-receipt" ? (
          <DisputedAmounts
            title="Potential unsupported invoice amount"
            emptyMessage="No unsupported invoice amounts."
            amounts={report.summary.unsupported_amounts}
          />
        ) : (
          <DisputedAmounts amounts={report.summary.disputed_amounts} />
        )}
      </div>
      <ResultsTable
        results={report.results}
        receiptCoverage={report.mode === "invoice-receipt"}
      />
    </>
  );
}
