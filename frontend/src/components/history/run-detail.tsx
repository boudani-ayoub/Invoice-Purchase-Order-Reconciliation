"use client";

import Link from "next/link";
import { useCallback } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { AnalysisResults } from "@/components/reconciliation/analysis-results";
import { Button } from "@/components/ui/button";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { HISTORY_PATH, RETENTION_COPY } from "@/constants/runs";
import { UPLOAD_FIELD_LABELS } from "@/constants/uploads";
import { useRunResource } from "@/hooks/use-run-resource";
import { getRun } from "@/lib/api/runs";
import { formatFileSize } from "@/lib/formatters";
import { RunActions } from "./run-actions";
import { RunDate } from "./run-summary";

export function RunDetailPage({ runId }: { runId: string }) {
  const auth = useAuth();
  const load = useCallback(
    (signal: AbortSignal) => getRun(runId, signal),
    [runId],
  );
  const resource = useRunResource(runId, load);
  const role = auth.session?.memberships.find(
    (membership) =>
      membership.organization_id === auth.session?.active_organization_id,
  )?.role;
  const canManage = role === "AP_MANAGER" || role === "ORG_ADMIN";
  const detail = resource.value;
  return (
    <div className="space-y-6">
      <Link
        href={HISTORY_PATH}
        className="text-sm font-medium text-primary underline"
      >
        Back to History
      </Link>
      {resource.loading && <p role="status">Loading saved run…</p>}
      {resource.error && (
        <div className="space-y-3">
          <h1 className="text-xl font-semibold">Saved run unavailable</h1>
          <p role="alert">{resource.error.message}</p>
          <Button variant="outline" onClick={resource.reload}>
            Try again
          </Button>
        </div>
      )}
      {detail && (
        <>
          <header className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-primary">
              Saved result{detail.run.archived_at ? " · Archived" : ""}
            </p>
            <h1 className="break-words text-2xl font-semibold">
              {detail.run.title ?? ANALYSIS_MODES[detail.run.mode].title}
            </h1>
            <p className="text-sm text-muted-foreground">
              {ANALYSIS_MODES[detail.run.mode].title} ·{" "}
              <RunDate value={detail.run.created_at} />
            </p>
            {detail.run.note && (
              <p className="whitespace-pre-wrap break-words text-sm">
                {detail.run.note}
              </p>
            )}
          </header>
          {canManage && (
            <RunActions
              key={`${detail.run.id}:${detail.run.version}`}
              run={detail.run}
              onChanged={resource.reload}
            />
          )}
          <section
            aria-labelledby="provenance-heading"
            className="space-y-3 rounded-lg border p-4"
          >
            <h2 id="provenance-heading" className="text-lg font-semibold">
              Source provenance
            </h2>
            <p className="text-sm text-muted-foreground">{RETENTION_COPY}</p>
            <p className="text-xs">
              Engine {detail.engine_version} · Report schema{" "}
              {detail.schema_version}
            </p>
            <ul className="space-y-4">
              {detail.sources.map((source) => (
                <li key={source.source_type} className="min-w-0 space-y-1">
                  <p className="break-words text-sm">
                    <span className="font-medium">
                      {UPLOAD_FIELD_LABELS[source.source_type]}:
                    </span>{" "}
                    {source.filename} · {formatFileSize(source.size_bytes)}
                  </p>
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground">
                      SHA-256 fingerprint
                    </summary>
                    <code className="block break-all py-2">
                      {source.sha256}
                    </code>
                  </details>
                </li>
              ))}
            </ul>
          </section>
          <section
            aria-labelledby="saved-results-heading"
            className="space-y-6"
          >
            <h2 id="saved-results-heading" className="text-xl font-semibold">
              {ANALYSIS_MODES[detail.run.mode].resultTitle}
            </h2>
            <p className="text-sm text-muted-foreground">
              This is the original saved result. Opening it does not run a new
              analysis.
            </p>
            <AnalysisResults report={detail.report} />
          </section>
        </>
      )}
    </div>
  );
}
