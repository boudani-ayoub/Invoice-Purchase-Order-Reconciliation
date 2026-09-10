"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RUN_NOTE_LIMIT, RUN_TITLE_LIMIT } from "@/constants/runs";
import { archiveRun, RunRequestError, updateRun } from "@/lib/api/runs";
import type { RunMetadata } from "@/types/runs";

function ArchiveConfirmation({
  busy,
  onConfirm,
  onCancel,
}: {
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  function cancel() {
    if (busy) return;
    dialog.current?.close();
    onCancel();
  }
  return (
    <dialog
      ref={dialog}
      aria-labelledby="archive-heading"
      aria-describedby="archive-explanation"
      onCancel={(event) => {
        event.preventDefault();
        cancel();
      }}
      className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-md space-y-4 rounded-lg border bg-card p-6 text-foreground shadow-lg backdrop:bg-black/40"
    >
      <h2 id="archive-heading" className="text-lg font-semibold">
        Archive this run?
      </h2>
      <p id="archive-explanation" className="text-sm">
        Archiving hides it from active history. It does not permanently erase
        source evidence, results, or audit data.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" disabled={busy} onClick={cancel} autoFocus>
          Cancel
        </Button>
        <Button disabled={busy} onClick={onConfirm}>
          {busy ? "Archiving…" : "Confirm archive"}
        </Button>
      </div>
    </dialog>
  );
}

export function RunActions({
  run,
  onChanged,
}: {
  run: RunMetadata;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [title, setTitle] = useState(run.title ?? "");
  const [note, setNote] = useState(run.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const archiveButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  useEffect(() => {
    if (editing) titleRef.current?.focus();
  }, [editing]);
  async function perform(action: () => Promise<RunMetadata>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setConfirming(false);
      onChanged();
    } catch (caught) {
      setConfirming(false);
      setError(
        caught instanceof Error
          ? caught
          : new Error("The change could not be saved."),
      );
    } finally {
      setBusy(false);
    }
  }
  const conflict = error instanceof RunRequestError && error.status === 409;
  return (
    <section
      aria-label="Run metadata controls"
      className="space-y-4 rounded-lg border p-4"
    >
      {error && (
        <div className="space-y-2">
          <p
            ref={errorRef}
            tabIndex={-1}
            role="alert"
            className="rounded-sm text-sm outline-none focus-visible:ring-2"
          >
            {error.message}
          </p>
          {conflict && (
            <Button variant="outline" onClick={onChanged}>
              Refresh run
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          disabled={busy || conflict}
          onClick={() => setEditing(!editing)}
        >
          {editing ? "Cancel editing" : "Edit metadata"}
        </Button>
        {run.archived_at ? (
          <Button
            variant="outline"
            disabled={busy || conflict}
            onClick={() =>
              void perform(() => archiveRun(run.id, run.version, false))
            }
          >
            Restore run
          </Button>
        ) : (
          <Button
            ref={archiveButton}
            variant="outline"
            disabled={busy || conflict}
            onClick={() => setConfirming(true)}
          >
            Archive run
          </Button>
        )}
      </div>
      {editing && (
        <form
          aria-label="Edit run metadata"
          className="max-w-2xl space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void perform(() =>
              updateRun(run.id, { title, note, expected_version: run.version }),
            );
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="run-title">Title</Label>
            <Input
              ref={titleRef}
              id="run-title"
              value={title}
              maxLength={RUN_TITLE_LIMIT}
              disabled={busy}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="run-note">Internal note</Label>
            <textarea
              id="run-note"
              value={note}
              maxLength={RUN_NOTE_LIMIT}
              disabled={busy}
              rows={4}
              onChange={(event) => setNote(event.target.value)}
              className="block w-full rounded-md border bg-background p-3 text-sm focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground">
              Plain text, visible to members of this organization. Maximum{" "}
              {RUN_NOTE_LIMIT} characters.
            </p>
          </div>
          <Button type="submit" disabled={busy || conflict}>
            {busy ? "Saving…" : "Save metadata"}
          </Button>
        </form>
      )}
      {confirming && (
        <ArchiveConfirmation
          busy={busy}
          onCancel={() => {
            setConfirming(false);
            archiveButton.current?.focus();
          }}
          onConfirm={() =>
            void perform(() => archiveRun(run.id, run.version, true))
          }
        />
      )}
    </section>
  );
}
