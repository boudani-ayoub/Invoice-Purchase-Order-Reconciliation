"use client";

import { useCallback, useState } from "react";
import { RunDate } from "@/components/history/run-summary";
import { Button } from "@/components/ui/button";
import { EVENT_LABELS, FINDING_STATUSES } from "@/constants/workflow";
import { useRunResource } from "@/hooks/use-run-resource";
import { listFindingEvents } from "@/lib/api/workflow";
import type { FindingEvent, FindingStatus } from "@/types/workflow";

function changeValue(event: FindingEvent, value: string | null | undefined) {
  if (value === null || value === undefined) return "Not set";
  if (["DUE_DATE_CHANGED", "REMINDER_CHANGED"].includes(event.event_type))
    return <RunDate value={value} />;
  if (Object.hasOwn(FINDING_STATUSES, value))
    return FINDING_STATUSES[value as FindingStatus];
  return value;
}
export function FindingTimeline({
  findingId,
  userId,
}: {
  findingId: string;
  userId?: string;
}) {
  const [cursors, setCursors] = useState<Array<string | undefined>>([
    undefined,
  ]);
  const cursor = cursors.at(-1);
  const load = useCallback(
    (signal: AbortSignal) => listFindingEvents(findingId, cursor, signal),
    [findingId, cursor],
  );
  const resource = useRunResource(JSON.stringify([findingId, cursor]), load);
  return (
    <section aria-labelledby="timeline-heading" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="timeline-heading" className="text-xl font-semibold">
          Workflow history
        </h2>
        <Button variant="outline" onClick={resource.reload}>
          Refresh history
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Append-only, newest first. Actor IDs and event versions retain
        attribution when membership or assignment changes.
      </p>
      {resource.loading && <p role="status">Loading workflow history…</p>}
      {resource.error && <p role="alert">{resource.error.message}</p>}
      {resource.value && (
        <>
          {!resource.value.items.length ? (
            <p className="rounded-lg border p-4 text-sm">
              No workflow changes or comments yet.
            </p>
          ) : (
            <ol className="divide-y rounded-lg border">
              {resource.value.items.map((event) => (
                <li key={event.id} className="min-w-0 space-y-2 p-4 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="font-semibold">
                      {EVENT_LABELS[event.event_type]}
                    </h3>
                    <RunDate value={event.created_at} />
                  </div>
                  <p className="break-words text-xs text-muted-foreground">
                    Actor:{" "}
                    {event.actor_user_id === userId
                      ? `You (${event.actor_user_id})`
                      : event.actor_user_id}
                    {event.metadata.new_version
                      ? ` · Finding version ${event.metadata.new_version}`
                      : ""}
                  </p>
                  {event.message && (
                    <p className="whitespace-pre-wrap break-words">
                      {event.message}
                    </p>
                  )}
                  {event.event_type !== "COMMENT_ADDED" && (
                    <p className="break-words">
                      {changeValue(event, event.metadata.previous)} →{" "}
                      {changeValue(event, event.metadata.new)}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
          <nav
            aria-label="Workflow history pagination"
            className="flex flex-wrap items-center gap-3"
          >
            <Button
              variant="outline"
              disabled={cursors.length === 1}
              onClick={() => setCursors((v) => v.slice(0, -1))}
            >
              Newer events
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
              Older events
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}
