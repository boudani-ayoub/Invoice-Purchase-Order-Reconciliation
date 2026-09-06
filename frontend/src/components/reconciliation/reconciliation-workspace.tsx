"use client";

import { useEffect, useRef } from "react";
import { RotateCcw } from "lucide-react";

import { DisputedAmounts } from "@/components/reconciliation/disputed-amounts";
import { FileUploadSection } from "@/components/reconciliation/file-upload-section";
import { IssueOverview } from "@/components/reconciliation/issue-overview";
import { ReconciliationError } from "@/components/reconciliation/reconciliation-error";
import { ReconciliationSummary } from "@/components/reconciliation/reconciliation-summary";
import { ResultsTable } from "@/components/reconciliation/results-table";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useReconciliation } from "@/hooks/use-reconciliation";

export function ReconciliationWorkspace() {
  const { files, report, error, isSubmitting, canSubmit, setFile, submit, reset } =
    useReconciliation();
  const resultsHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (report) {
      resultsHeading.current?.focus({ preventScroll: true });
      resultsHeading.current?.scrollIntoView({ block: "start" });
    }
  }, [report]);

  return (
    <div className="space-y-10" aria-busy={isSubmitting}>
      <FileUploadSection
        files={files}
        canSubmit={canSubmit}
        isSubmitting={isSubmitting}
        onFileChange={setFile}
        onSubmit={submit}
      />

      {error ? <ReconciliationError error={error} onRetry={submit} /> : null}

      {report ? (
        <section aria-labelledby="results-heading" className="scroll-mt-6 space-y-6">
          <Separator />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold tracking-wider text-primary uppercase">Outcome</p>
              <h2
                id="results-heading"
                ref={resultsHeading}
                tabIndex={-1}
                className="mt-1 text-xl font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                Reconciliation results
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Review exceptions first, then inspect matched lines when needed.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={reset}>
              <RotateCcw aria-hidden="true" data-icon="inline-start" />
              Start new reconciliation
            </Button>
          </div>

          <ReconciliationSummary summary={report.summary} />
          <div className="grid gap-4 lg:grid-cols-3">
            <IssueOverview issueCounts={report.summary.issue_counts} />
            <DisputedAmounts amounts={report.summary.disputed_amounts} />
          </div>
          <ResultsTable results={report.results} />
        </section>
      ) : null}
    </div>
  );
}
