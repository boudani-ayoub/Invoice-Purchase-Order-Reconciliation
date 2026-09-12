"use client";

import { useCallback, useState } from "react";
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
import { useRunResource } from "@/hooks/use-run-resource";
import { getWorkload } from "@/lib/api/dashboard";

export function Workload() {
  const [cursors, setCursors] = useState<Array<string | undefined>>([
    undefined,
  ]);
  const cursor = cursors.at(-1);
  const load = useCallback(
    (signal: AbortSignal) => getWorkload(cursor, signal),
    [cursor],
  );
  const resource = useRunResource(cursor ?? "first", load);
  return (
    <section aria-labelledby="workload-title" className="min-w-0 space-y-4">
      <h2 id="workload-title" className="text-xl font-semibold">
        Current workload
      </h2>
      <p className="text-sm text-muted-foreground">
        Unresolved findings by assignee. Inactive assignments remain included;
        Unassigned is shown on every page.
      </p>
      {resource.loading && <p role="status">Loading workload…</p>}
      {resource.error && (
        <div className="space-y-2">
          <p role="alert">{resource.error.message}</p>
          <Button onClick={resource.reload} variant="outline">
            Retry workload
          </Button>
        </div>
      )}
      {resource.value && (
        <>
          <Table
            aria-label="Current assignee workload"
            scrollLabel="Workload table scroll area"
          >
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Assignee</TableHead>
                <TableHead scope="col">Open</TableHead>
                <TableHead scope="col">In review</TableHead>
                <TableHead scope="col">Unresolved</TableHead>
                <TableHead scope="col">Overdue</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[resource.value.unassigned, ...resource.value.items].map(
                (row) => (
                  <TableRow key={row.assignee_user_id ?? "unassigned"}>
                    <TableHead
                      scope="row"
                      className="max-w-64 whitespace-normal break-words"
                    >
                      {row.assignee_user_id
                        ? (row.display_name ?? row.assignee_user_id)
                        : "Unassigned"}
                      {row.active === false && (
                        <span className="block text-xs text-muted-foreground">
                          Inactive
                        </span>
                      )}
                      {row.role && (
                        <span className="block text-xs font-normal text-muted-foreground">
                          {row.role.toLowerCase().replaceAll("_", " ")}
                        </span>
                      )}
                    </TableHead>
                    <TableCell>{row.open}</TableCell>
                    <TableCell>{row.in_review}</TableCell>
                    <TableCell className="font-semibold">
                      {row.unresolved}
                    </TableCell>
                    <TableCell>{row.overdue}</TableCell>
                  </TableRow>
                ),
              )}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">
            Checked <RunDate value={resource.value.server_now} />.
          </p>
          <nav
            aria-label="Workload pagination"
            className="flex flex-wrap items-center gap-3"
          >
            <Button
              variant="outline"
              disabled={cursors.length === 1}
              onClick={() => setCursors((v) => v.slice(0, -1))}
            >
              Previous assignees
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
              Next assignees
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}
