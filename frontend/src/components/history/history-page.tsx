"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { RETENTION_COPY, runPath } from "@/constants/runs";
import { useRunResource } from "@/hooks/use-run-resource";
import { listRuns } from "@/lib/api/runs";
import type { AnalysisMode } from "@/types/analysis";
import { RunDate, RunSummary } from "./run-summary";

export function HistoryPage() {
  const [filter, setFilter] = useState<{
    mode: AnalysisMode | "";
    archived: boolean;
  }>({ mode: "", archived: false });
  const [cursors, setCursors] = useState<Array<string | undefined>>([
    undefined,
  ]);
  const cursor = cursors.at(-1);
  const load = useCallback(
    (signal: AbortSignal) =>
      listRuns(
        { mode: filter.mode || undefined, archived: filter.archived, cursor },
        signal,
      ),
    [filter, cursor],
  );
  const resource = useRunResource(JSON.stringify([filter, cursor]), load);
  function change(next: typeof filter) {
    setFilter(next);
    setCursors([undefined]);
  }
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">History</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          {RETENTION_COPY}
        </p>
      </header>
      <div className="flex flex-wrap gap-4">
        <label className="space-y-1 text-sm font-medium">
          Analysis type
          <select
            className="block rounded-md border bg-background p-2"
            value={filter.mode}
            onChange={(event) =>
              change({
                ...filter,
                mode: event.target.value as AnalysisMode | "",
              })
            }
          >
            <option value="">All analysis types</option>
            {Object.values(ANALYSIS_MODES).map((mode) => (
              <option key={mode.id} value={mode.id}>
                {mode.title}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm font-medium">
          History status
          <select
            className="block rounded-md border bg-background p-2"
            value={String(filter.archived)}
            onChange={(event) =>
              change({ ...filter, archived: event.target.value === "true" })
            }
          >
            <option value="false">Active runs</option>
            <option value="true">Archived runs</option>
          </select>
        </label>
      </div>
      {resource.loading && <p role="status">Loading history…</p>}
      {resource.error && (
        <div className="space-y-3">
          <p role="alert">{resource.error.message}</p>
          <Button variant="outline" onClick={resource.reload}>
            Try again
          </Button>
        </div>
      )}
      {resource.value && (
        <>
          {!resource.value.items.length ? (
            <p className="rounded-lg border p-6">
              {filter.archived
                ? "No archived runs."
                : "No saved runs match this view. Run an analysis to start your history."}
            </p>
          ) : (
            <ul className="divide-y rounded-lg border bg-card">
              {resource.value.items.map((run) => (
                <li key={run.id} className="space-y-2 p-4 sm:p-5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <Link
                      className="min-w-0 break-words font-semibold text-primary underline-offset-4 hover:underline"
                      href={runPath(run.id)}
                    >
                      {run.title ?? ANALYSIS_MODES[run.mode].title}
                    </Link>
                    <span className="text-xs text-muted-foreground">
                      {run.archived_at ? "Archived" : "Completed"}
                    </span>
                  </div>
                  <p className="text-sm">
                    {ANALYSIS_MODES[run.mode].title} ·{" "}
                    <RunDate value={run.created_at} />
                  </p>
                  <RunSummary run={run} />
                </li>
              ))}
            </ul>
          )}
          <nav
            aria-label="History pagination"
            className="flex items-center gap-3"
          >
            <Button
              variant="outline"
              disabled={cursors.length === 1}
              onClick={() => setCursors((current) => current.slice(0, -1))}
            >
              Previous page
            </Button>
            <span className="text-sm">Page {cursors.length}</span>
            <Button
              variant="outline"
              disabled={!resource.value.next_cursor}
              onClick={() =>
                setCursors((current) => [
                  ...current,
                  resource.value?.next_cursor ?? undefined,
                ])
              }
            >
              Next page
            </Button>
          </nav>
        </>
      )}
    </div>
  );
}
