"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { runPath } from "@/constants/runs";
import { RotateCcw } from "lucide-react";

import { FileUploadSection } from "@/components/reconciliation/file-upload-section";
import { ReconciliationError } from "@/components/reconciliation/reconciliation-error";
import { AnalysisResults } from "@/components/reconciliation/analysis-results";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { UPLOAD_FIELD_LABELS } from "@/constants/uploads";
import type { AnalysisMode } from "@/types/analysis";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useReconciliation } from "@/hooks/use-reconciliation";

export function ReconciliationWorkspace({ mode }: { mode?: AnalysisMode }) {
  const definition = ANALYSIS_MODES[mode ?? "three-way"];
  const {
    files,
    report,
    savedRunId,
    error,
    isSubmitting,
    canSubmit,
    setFile,
    submit,
    reset,
  } = useReconciliation(mode);
  const resultsHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (report) {
      resultsHeading.current?.focus({ preventScroll: true });
      resultsHeading.current?.scrollIntoView({ block: "start" });
    }
  }, [report]);

  return (
    <div className="space-y-10" aria-busy={isSubmitting}>
      <section aria-label="Analysis scope" className="space-y-3">
        {mode ? (
          <h1 className="text-2xl font-semibold tracking-tight">
            {definition.title}
          </h1>
        ) : null}
        <p className="text-lg">{definition.question}</p>
        <dl className="space-y-2 text-sm leading-6">
          <div>
            <dt className="inline font-semibold">Data used: </dt>
            <dd className="inline">
              {definition.requiredSources
                .map((source) => UPLOAD_FIELD_LABELS[source])
                .join(", ")}
            </dd>
          </div>
          <div>
            <dt className="inline font-semibold">Controls performed: </dt>
            <dd className="inline">{definition.controls}</dd>
          </div>
          <div>
            <dt className="inline font-semibold">Controls not performed: </dt>
            <dd className="inline text-muted-foreground">
              {definition.limitations}
            </dd>
          </div>
        </dl>
      </section>
      <FileUploadSection
        definition={definition}
        files={files}
        canSubmit={canSubmit}
        isSubmitting={isSubmitting}
        onFileChange={setFile}
        onSubmit={submit}
      />

      {error ? <ReconciliationError error={error} onRetry={submit} /> : null}

      {report ? (
        <section
          aria-labelledby="results-heading"
          className="scroll-mt-6 space-y-6"
        >
          <Separator />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold tracking-wider text-primary uppercase">
                Outcome
              </p>
              <h2
                id="results-heading"
                ref={resultsHeading}
                tabIndex={-1}
                className="mt-1 text-xl font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {definition.resultTitle}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {mode === "po-receipt"
                  ? "Review delivery progress and unresolved receipts."
                  : "Review exceptions first, then inspect matched lines when needed."}
              </p>
            </div>
            <Button type="button" variant="outline" onClick={reset}>
              <RotateCcw aria-hidden="true" data-icon="inline-start" />
              {mode === "po-receipt"
                ? "Start new analysis"
                : "Start new reconciliation"}
            </Button>
          </div>

          <AnalysisResults report={report} />
          {savedRunId && (
            <p role="status" className="text-sm">
              Saved to history.{" "}
              <Link
                className="font-medium text-primary underline"
                href={runPath(savedRunId)}
              >
                View saved run
              </Link>
            </p>
          )}
        </section>
      ) : null}
    </div>
  );
}
