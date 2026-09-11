"use client";

import Link from "next/link";
import { useCallback, useId, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { RunDate } from "@/components/history/run-summary";
import { Button } from "@/components/ui/button";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { getIssuePresentation } from "@/constants/issues";
import { runPath } from "@/constants/runs";
import {
  FINDING_STATUSES,
  WORKFLOW_REMINDER_COPY,
  WORK_PATH,
  findingPath,
} from "@/constants/workflow";
import { useRunResource } from "@/hooks/use-run-resource";
import { listFindings } from "@/lib/api/workflow";
import type { Finding, FindingStatus } from "@/types/workflow";

export function AssigneeName({
  finding,
  userId,
}: {
  finding: Finding;
  userId?: string;
}) {
  if (!finding.assignee_user_id) return <>Unassigned</>;
  return (
    <>
      {finding.assignee_user_id === userId
        ? "You"
        : (finding.assignee?.display_name ?? finding.assignee_user_id)}
      {finding.assignee?.active === false ? " (inactive)" : ""}
    </>
  );
}
export function WorkflowSchedule({ finding }: { finding: Finding }) {
  return (
    <>
      <div>
        <dt className="text-xs text-muted-foreground">Due date</dt>
        <dd>
          {finding.due_at ? <RunDate value={finding.due_at} /> : "Not set"}
          {finding.overdue && (
            <strong className="block text-sm text-foreground">Overdue</strong>
          )}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Reminder</dt>
        <dd>
          {finding.reminder_at ? (
            <RunDate value={finding.reminder_at} />
          ) : (
            "Not set"
          )}
          {finding.reminder_due && (
            <strong className="block text-sm">Reminder due</strong>
          )}
        </dd>
      </div>
    </>
  );
}

export function WorkQueue({ runId }: { runId?: string }) {
  const statusId = useId();
  const assignmentId = useId();
  const auth = useAuth();
  const [filter, setFilter] = useState({
    status: "" as FindingStatus | "",
    assignee: "",
    overdue: false,
    reminder_due: false,
  });
  const [cursors, setCursors] = useState<Array<string | undefined>>([
    undefined,
  ]);
  const cursor = cursors.at(-1);
  const load = useCallback(
    (signal: AbortSignal) =>
      listFindings(
        {
          run_id: runId,
          status: filter.status || undefined,
          assignee: filter.assignee || undefined,
          overdue: filter.overdue || undefined,
          reminder_due: filter.reminder_due || undefined,
          cursor,
        },
        signal,
      ),
    [filter, runId, cursor],
  );
  const resource = useRunResource(
    JSON.stringify([runId, filter, cursor]),
    load,
  );
  function change(next: typeof filter) {
    setFilter(next);
    setCursors([undefined]);
  }
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Work</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Investigate findings from saved analyses. Workflow includes findings
          from archived runs; archiving is not deletion.
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {WORKFLOW_REMINDER_COPY}
        </p>
        {runId && (
          <p className="flex flex-wrap gap-3 text-sm">
            <Link className="text-primary underline" href={runPath(runId)}>
              Back to originating run
            </Link>
            <Link className="text-primary underline" href={WORK_PATH}>
              Show all runs
            </Link>
          </p>
        )}
      </header>
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1 text-sm font-medium">
          <label htmlFor={statusId}>Workflow status</label>
          <select
            id={statusId}
            className="block rounded-md border bg-background p-2"
            value={filter.status}
            onChange={(e) =>
              change({
                ...filter,
                status: e.target.value as FindingStatus | "",
              })
            }
          >
            <option value="">All statuses</option>
            {Object.entries(FINDING_STATUSES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1 text-sm font-medium">
          <label htmlFor={assignmentId}>Assignment</label>
          <select
            id={assignmentId}
            className="block rounded-md border bg-background p-2"
            value={filter.assignee}
            onChange={(e) => change({ ...filter, assignee: e.target.value })}
          >
            <option value="">Everyone</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </div>
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={filter.overdue}
            onChange={(e) => change({ ...filter, overdue: e.target.checked })}
          />
          Overdue only
        </label>
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={filter.reminder_due}
            onChange={(e) =>
              change({ ...filter, reminder_due: e.target.checked })
            }
          />
          Reminder due only
        </label>
        <Button variant="outline" onClick={resource.reload}>
          Refresh queue
        </Button>
      </div>
      {resource.loading && <p role="status">Loading work queue…</p>}
      {resource.error && (
        <div className="space-y-2">
          <p role="alert">{resource.error.message}</p>
          <Button variant="outline" onClick={resource.reload}>
            Try again
          </Button>
        </div>
      )}
      {resource.value && (
        <>
          <p className="text-xs text-muted-foreground">
            Due states checked at <RunDate value={resource.value.server_now} />.
            Displayed dates use your local timezone.
          </p>
          {!resource.value.items.length ? (
            <p className="rounded-lg border p-6">
              No findings match this view.
            </p>
          ) : (
            <ul
              aria-label="Finding queue"
              className="divide-y rounded-lg border bg-card"
            >
              {resource.value.items.map((finding) => (
                <li key={finding.id} className="min-w-0 space-y-3 p-4 sm:p-5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <Link
                      prefetch={false}
                      href={findingPath(finding.id)}
                      className="min-w-0 break-words font-semibold text-primary underline-offset-4 hover:underline"
                    >
                      {getIssuePresentation(finding.code).label}
                    </Link>
                    <span className="rounded border px-2 py-1 text-xs">
                      {FINDING_STATUSES[finding.status]}
                    </span>
                  </div>
                  <p className="break-words text-sm">
                    {finding.reference.invoice_number
                      ? `Invoice ${finding.reference.invoice_number} · line ${finding.reference.invoice_line_number}`
                      : finding.reference.receipt_number
                        ? `Receipt ${finding.reference.receipt_number} · line ${finding.reference.receipt_line_number}`
                        : `PO ${finding.reference.po_number} · line ${finding.reference.po_line_number}`}{" "}
                    · Item {finding.reference.item_code}
                  </p>
                  <dl className="grid gap-3 break-words text-sm sm:grid-cols-2 lg:grid-cols-4">
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        Assignee
                      </dt>
                      <dd>
                        <AssigneeName
                          finding={finding}
                          userId={auth.session?.user.id}
                        />
                      </dd>
                    </div>
                    <WorkflowSchedule finding={finding} />
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        Originating run
                      </dt>
                      <dd>
                        <Link
                          className="text-primary underline"
                          href={runPath(finding.run.id)}
                        >
                          {finding.run.title ??
                            ANALYSIS_MODES[finding.run.mode].title}
                        </Link>
                        {finding.run.archived && " · Archived"}
                      </dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
          <nav
            aria-label="Work pagination"
            className="flex flex-wrap items-center gap-3"
          >
            <Button
              variant="outline"
              disabled={cursors.length === 1}
              onClick={() => setCursors((v) => v.slice(0, -1))}
            >
              Previous page
            </Button>
            <span className="text-sm">Page {cursors.length}</span>
            <Button
              variant="outline"
              disabled={!resource.value.next_cursor}
              onClick={() =>
                setCursors((v) => [
                  ...v,
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
