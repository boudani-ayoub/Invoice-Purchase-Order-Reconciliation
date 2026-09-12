"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { RunDate } from "@/components/history/run-summary";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ACTIVITY_SERIES,
  canViewDashboard,
  DEFAULT_REPORTING_WINDOW,
  RECENT_RUN_LIMIT,
  REPORTING_WINDOWS,
} from "@/constants/dashboard";
import { getIssuePresentation } from "@/constants/issues";
import { WORK_PATH } from "@/constants/workflow";
import { useRunResource } from "@/hooks/use-run-resource";
import { getIssues, getOverview, getTrends } from "@/lib/api/dashboard";
import { listRuns } from "@/lib/api/runs";
import type { ReportingWindow } from "@/types/dashboard";
import { ActivityTrend } from "./activity-trend";
import { RecentRuns } from "./recent-runs";
import { Workload } from "./workload";

export function DashboardPage() {
  const auth = useAuth();
  const role = auth.session?.memberships.find(
    (m) => m.organization_id === auth.session?.active_organization_id,
  )?.role;
  if (!canViewDashboard(role))
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold">Dashboard access required</h1>
        <p>
          The manager dashboard is available to AP managers and organization
          administrators.
        </p>
        <Link href={WORK_PATH} className="text-primary underline">
          Go to Work
        </Link>
      </div>
    );
  return <ManagerDashboard />;
}
function ageText(seconds: number | null) {
  if (seconds === null) return "No unresolved findings";
  if (seconds < 0) return "Clock discrepancy";
  if (seconds > 0 && seconds < 8640) return "< 0.1 days";
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(seconds / 86400)} days`;
}
function ManagerDashboard() {
  const auth = useAuth();
  const [window, setWindow] = useState<ReportingWindow>(
    DEFAULT_REPORTING_WINDOW,
  );
  const [refresh, setRefresh] = useState(0);
  const selectId = useId();
  const errorRef = useRef<HTMLParagraphElement>(null);
  const load = useCallback(
    async (signal: AbortSignal) => {
      const [overview, trends, issues, recent] = await Promise.all([
        getOverview(window, signal),
        getTrends(window, signal),
        getIssues(signal),
        listRuns({ archived: false, limit: RECENT_RUN_LIMIT }, signal),
      ]);
      return { overview, trends, issues, recent };
    },
    [window],
  );
  const resource = useRunResource(`${window}:${refresh}`, load);
  useEffect(() => {
    if (resource.error) errorRef.current?.focus();
  }, [resource.error]);
  const data = resource.value;
  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">AP manager dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Finding workload and recorded workflow activity.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor={selectId} className="block text-sm font-medium">
              Activity window
            </label>
            <select
              id={selectId}
              value={window}
              onChange={(e) => setWindow(e.target.value as ReportingWindow)}
              className="rounded-md border bg-background p-2 text-sm"
            >
              {Object.entries(REPORTING_WINDOWS).map(([key, days]) => (
                <option key={key} value={key}>
                  {days} UTC days
                </option>
              ))}
            </select>
          </div>
          <Button variant="outline" onClick={() => setRefresh((v) => v + 1)}>
            Refresh dashboard
          </Button>
        </div>
      </header>
      {resource.loading && <p role="status">Loading dashboard…</p>}
      {resource.error && (
        <div className="space-y-3">
          <p
            role="alert"
            ref={errorRef}
            tabIndex={-1}
            className="focus-visible:ring-2"
          >
            {resource.error.message}
          </p>
          <Button
            variant="outline"
            onClick={() => {
              void auth.refresh();
              setRefresh((v) => v + 1);
            }}
          >
            Retry dashboard
          </Button>
        </div>
      )}
      {data && (
        <>
          <section aria-labelledby="backlog-title" className="space-y-4">
            <div className="flex flex-wrap justify-between gap-3">
              <h2 id="backlog-title" className="text-xl font-semibold">
                Current backlog
              </h2>
              <Link href={WORK_PATH} className="text-sm text-primary underline">
                Open Work queue
              </Link>
            </div>
            <p className="text-sm text-muted-foreground">
              All saved findings, including archived runs. Not limited by the
              activity window; repeated analyses create separate findings.
            </p>
            <dl className="grid grid-cols-2 divide-x rounded-md border bg-card lg:grid-cols-4">
              {(
                [
                  ["Unresolved", data.overview.backlog.unresolved],
                  ["In review", data.overview.backlog.in_review],
                  ["Overdue", data.overview.backlog.overdue],
                  ["Unassigned", data.overview.backlog.unassigned_unresolved],
                ] as const
              ).map(([name, value]) => (
                <div key={name} className="space-y-2 p-4">
                  <dt className="text-sm font-medium">{name}</dt>
                  <dd className="text-3xl font-semibold tabular-nums">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-sm">
              Open: {data.overview.backlog.open} · Currently resolved:{" "}
              {data.overview.backlog.resolved} · Reminder due:{" "}
              {data.overview.backlog.reminder_due}
            </p>
            <p className="text-xs text-muted-foreground">
              Checked <RunDate value={data.overview.server_now} />. Unresolved
              means Open or In review. Overdue excludes due times equal to this
              check time.
            </p>
          </section>
          <section aria-labelledby="activity-title" className="space-y-4">
            <h2 id="activity-title" className="text-xl font-semibold">
              Period activity
            </h2>
            <p className="text-sm text-muted-foreground">
              UTC calendar days, including today so far. Start included; end
              excluded. Resolution and reopen counts are actions, not unique or
              permanently closed cases.
            </p>
            <p className="break-words text-xs text-muted-foreground">
              {data.overview.period.start} to {data.overview.period.end}
            </p>
            <dl className="flex flex-wrap gap-x-10 gap-y-4">
              {ACTIVITY_SERIES.map((s) => (
                <div key={s.key}>
                  <dt className="text-sm">{s.label}</dt>
                  <dd className="text-2xl font-semibold tabular-nums">
                    {data.overview.activity[s.key]}
                  </dd>
                </div>
              ))}
            </dl>
            <ActivityTrend trends={data.trends} />
            <p className="text-xs text-muted-foreground">
              Trend checked <RunDate value={data.trends.server_now} />. Sections
              are independent reads and can differ while colleagues work.
            </p>
          </section>
          <div className="grid gap-8 lg:grid-cols-[2fr_1fr]">
            <section
              aria-labelledby="issues-title"
              className="min-w-0 space-y-4"
            >
              <h2 id="issues-title" className="text-xl font-semibold">
                Unresolved issue mix
              </h2>
              {!data.issues.items.length ? (
                <p className="text-sm">No unresolved findings.</p>
              ) : (
                <Table
                  aria-label="Unresolved issue counts"
                  scrollLabel="Issue table scroll area"
                >
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">Issue</TableHead>
                      <TableHead scope="col">Category</TableHead>
                      <TableHead scope="col">Findings</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.issues.items.map((row) => (
                      <TableRow key={`${row.code}:${row.category}`}>
                        <TableHead scope="row" className="whitespace-normal">
                          {getIssuePresentation(row.code).label}
                          <span className="block text-xs font-normal text-muted-foreground">
                            {row.code}
                          </span>
                        </TableHead>
                        <TableCell>{row.category.toLowerCase()}</TableCell>
                        <TableCell>{row.count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <p className="text-xs text-muted-foreground">
                Current counts, not error rates. Checked{" "}
                <RunDate value={data.issues.server_now} />.
              </p>
            </section>
            <section aria-labelledby="age-title" className="space-y-4">
              <h2 id="age-title" className="text-xl font-semibold">
                Unresolved age
              </h2>
              <p className="text-sm text-muted-foreground">
                Elapsed time since finding creation, including time before any
                reopen. Not time to resolution.
              </p>
              <dl className="space-y-4">
                <div>
                  <dt className="text-sm">Median age</dt>
                  <dd className="text-xl font-semibold">
                    {ageText(data.overview.age.median_unresolved_age_seconds)}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm">Oldest age</dt>
                  <dd className="text-xl font-semibold">
                    {ageText(data.overview.age.oldest_unresolved_age_seconds)}
                  </dd>
                </div>
              </dl>
            </section>
          </div>
          <Workload key={`${window}:${refresh}`} />
          <RecentRuns runs={data.recent.items} />
        </>
      )}
    </div>
  );
}
