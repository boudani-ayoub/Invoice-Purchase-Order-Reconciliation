"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { listAssignees } from "@/lib/api/workflow";
import type { Assignee, Finding } from "@/types/workflow";

export function AssigneePicker({
  finding,
  value,
  onChange,
  disabled,
}: {
  finding: Finding;
  value: string;
  onChange: (id: string) => void;
  disabled: boolean;
}) {
  const selectId = useId();
  const [items, setItems] = useState<Assignee[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void listAssignees(undefined, controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) {
          setItems(result.items);
          setCursor(result.next_cursor);
          setBusy(false);
        }
      },
      (caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Unable to load assignees.",
          );
          setBusy(false);
        }
      },
    );
    return () => controller.abort();
  }, []);
  async function more() {
    setBusy(true);
    setError(null);
    try {
      const result = await listAssignees(cursor ?? undefined);
      setItems((previous) => [
        ...previous,
        ...result.items.filter(
          (item) => !previous.some((p) => p.user_id === item.user_id),
        ),
      ]);
      setCursor(result.next_cursor);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unable to load assignees.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-2">
      <label htmlFor={selectId} className="block text-sm font-medium">
        Assignee
      </label>
      <select
        id={selectId}
        className="block w-full min-w-0 rounded-md border bg-background p-2"
        value={value}
        disabled={disabled || busy}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Unassigned</option>
        {finding.assignee_user_id &&
          !items.some((item) => item.user_id === finding.assignee_user_id) && (
            <option value={finding.assignee_user_id}>
              {finding.assignee?.display_name ?? finding.assignee_user_id}
              {finding.assignee?.active === false
                ? " (inactive)"
                : " (current)"}
            </option>
          )}
        {items.map((item) => (
          <option key={item.user_id} value={item.user_id}>
            {item.display_name} · {item.role.toLowerCase().replaceAll("_", " ")}
          </option>
        ))}
      </select>
      {busy && (
        <p role="status" className="text-xs">
          Loading organization members…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm">
          {error}
        </p>
      )}
      {(cursor || error) && (
        <Button
          type="button"
          variant="outline"
          disabled={busy || disabled}
          onClick={() => void more()}
        >
          {error ? "Retry member list" : "Load more members"}
        </Button>
      )}
    </div>
  );
}
