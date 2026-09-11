"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
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
  runWorkPath,
} from "@/constants/workflow";
import { useRunResource } from "@/hooks/use-run-resource";
import { getFinding } from "@/lib/api/workflow";
import { FindingTimeline } from "./finding-timeline";
import { AssigneeName, WorkflowSchedule } from "./work-queue";
import { WorkflowControls } from "./workflow-controls";

export function FindingDetailPage({ findingId }: { findingId: string }) {
  const auth = useAuth();
  const [timelineRevision, setTimelineRevision] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => getFinding(findingId, signal),
    [findingId],
  );
  const resource = useRunResource(findingId, load);
  const heading = useRef<HTMLHeadingElement>(null);
  const finding = resource.value?.finding;
  useEffect(() => {
    if (finding) heading.current?.focus();
  }, [finding]);
  const reference = finding?.reference;
  return (
    <div className="space-y-6">
      <Link href={WORK_PATH} className="text-sm text-primary underline">
        Back to Work
      </Link>
      {resource.loading && <p role="status">Loading finding…</p>}
      {resource.error && (
        <div className="space-y-3">
          <h1 className="text-xl font-semibold">Finding unavailable</h1>
          <p role="alert">{resource.error.message}</p>
          <Button variant="outline" onClick={resource.reload}>
            Try again
          </Button>
        </div>
      )}
      {finding && reference && (
        <>
          <header className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-primary">
              Finding workflow · Version {finding.version}
            </p>
            <h1
              ref={heading}
              tabIndex={-1}
              className="break-words text-2xl font-semibold focus-visible:ring-2"
            >
              {getIssuePresentation(finding.code).label}
            </h1>
            <p className="text-sm text-muted-foreground">
              {getIssuePresentation(finding.code).description}
            </p>
            <p className="break-words text-xs">
              {finding.code} · {finding.category}
            </p>
          </header>
          <section
            aria-labelledby="context-heading"
            className="space-y-4 rounded-lg border p-4 sm:p-5"
          >
            <h2 id="context-heading" className="text-lg font-semibold">
              Source context
            </h2>
            <p className="break-words text-sm">
              <Link
                className="text-primary underline"
                href={runPath(finding.run.id)}
              >
                {finding.run.title ?? ANALYSIS_MODES[finding.run.mode].title}
              </Link>
              {finding.run.archived && " · Archived run"} ·{" "}
              <Link
                className="text-primary underline"
                href={runWorkPath(finding.run.id)}
              >
                All findings from this run
              </Link>
            </p>
            <dl className="grid gap-3 break-words text-sm sm:grid-cols-2 lg:grid-cols-3">
              {reference.invoice_number && (
                <div>
                  <dt className="text-xs text-muted-foreground">Invoice</dt>
                  <dd>
                    {reference.invoice_number} · line{" "}
                    {reference.invoice_line_number}
                  </dd>
                </div>
              )}
              {reference.receipt_number && (
                <div>
                  <dt className="text-xs text-muted-foreground">Receipt</dt>
                  <dd>
                    {reference.receipt_number} · line{" "}
                    {reference.receipt_line_number}
                  </dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-muted-foreground">
                  Purchase order reference
                </dt>
                <dd>
                  {reference.po_number} · line {reference.po_line_number}
                  {!reference.po_reference_resolved && (
                    <span className="block">Unresolved source reference</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Item code</dt>
                <dd>
                  {reference.item_code}
                  {!reference.item_master_resolved && (
                    <span className="block text-xs">
                      No resolved item master
                    </span>
                  )}
                </dd>
              </div>
              {reference.supplier_code && (
                <div>
                  <dt className="text-xs text-muted-foreground">
                    Supplier code
                  </dt>
                  <dd>{reference.supplier_code}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-muted-foreground">
                  Original source row
                </dt>
                <dd>{reference.source_row_number}</dd>
              </div>
            </dl>
            <p className="text-xs text-muted-foreground">
              References are persisted evidence, not newly created master
              records. The originating saved report remains the authoritative
              analysis.
            </p>
          </section>
          <section
            aria-labelledby="state-heading"
            className="space-y-4 rounded-lg border p-4 sm:p-5"
          >
            <h2 id="state-heading" className="text-lg font-semibold">
              Current workflow
            </h2>
            <dl className="grid gap-3 break-words text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-xs text-muted-foreground">Status</dt>
                <dd>{FINDING_STATUSES[finding.status]}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Assignee</dt>
                <dd>
                  <AssigneeName
                    finding={finding}
                    userId={auth.session?.user.id}
                  />
                </dd>
              </div>
              <WorkflowSchedule finding={finding} />
            </dl>
            <p className="text-xs text-muted-foreground">
              {WORKFLOW_REMINDER_COPY}
            </p>
            <p className="text-xs text-muted-foreground">
              Displayed dates use your local timezone. Due states checked at{" "}
              <RunDate value={resource.value!.server_now} />.
            </p>
            {finding.resolved_at && (
              <div className="space-y-2 text-sm">
                <p className="break-words">
                  Resolved <RunDate value={finding.resolved_at} /> by{" "}
                  {finding.resolved_by_user_id}
                </p>
                <p className="whitespace-pre-wrap break-words">
                  {finding.resolution_note}
                </p>
              </div>
            )}
          </section>
          <WorkflowControls
            key={`${finding.id}:${finding.version}`}
            finding={finding}
            onChanged={resource.reload}
            onComment={() => setTimelineRevision((v) => v + 1)}
          />
          <FindingTimeline
            key={`${finding.id}:${finding.version}:${timelineRevision}`}
            findingId={finding.id}
            userId={auth.session?.user.id}
          />
        </>
      )}
    </div>
  );
}
