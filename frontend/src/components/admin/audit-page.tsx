"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getAudit } from "@/lib/api/admin";
import type { AuditEntry } from "@/types/admin";

const title = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

export function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await getAudit();
      setItems(page.items);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Audit activity could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const pending = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(pending);
  }, [refresh]);

  async function more() {
    if (!cursor || loading) return;
    setLoading(true);
    setError(null);
    try {
      const page = await getAudit(cursor);
      setItems((current) => [...current, ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "More activity could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-5" aria-labelledby="audit-title">
      <div>
        <h1 id="audit-title" className="text-2xl font-semibold">
          Organization audit
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          A retained, read-only timeline of run, finding workflow, and
          organization-governance events. Workflow comment and resolution
          bodies remain in their original workflow context and are not shown here.
        </p>
      </div>
      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 p-3 text-sm text-destructive">
          <span>{error}</span>
          <Button variant="outline" onClick={() => void refresh()}>
            Retry
          </Button>
        </div>
      )}
      {!items.length && loading ? (
        <p role="status">Loading organization activity…</p>
      ) : !items.length ? (
        <p className="text-sm text-muted-foreground">No organization activity yet.</p>
      ) : (
        <Table aria-label="Organization audit events" scrollLabel="Audit table scroll area">
          <TableHeader>
            <TableRow>
              <TableHead scope="col">When</TableHead>
              <TableHead scope="col">Source</TableHead>
              <TableHead scope="col">Activity</TableHead>
              <TableHead scope="col">Actor</TableHead>
              <TableHead scope="col">Target</TableHead>
              <TableHead scope="col">Request</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((entry) => (
              <TableRow key={`${entry.source}:${entry.id}`}>
                <TableCell>{new Date(entry.created_at).toLocaleString()}</TableCell>
                <TableCell>{title(entry.source)}</TableCell>
                <TableCell>{title(entry.event_type)}</TableCell>
                <TableCell className="max-w-56 whitespace-normal break-words">
                  {entry.actor_display_name}
                </TableCell>
                <TableCell>
                  <span className="block">{title(entry.resource_type)}</span>
                  <span className="block max-w-48 truncate font-mono text-xs" title={entry.resource_id}>
                    {entry.resource_id}
                  </span>
                </TableCell>
                <TableCell>
                  <span className="block max-w-48 truncate font-mono text-xs" title={entry.request_id}>
                    {entry.request_id}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {cursor && (
        <Button variant="outline" onClick={() => void more()} disabled={loading}>
          {loading ? "Loading…" : "Load older activity"}
        </Button>
      )}
    </section>
  );
}
