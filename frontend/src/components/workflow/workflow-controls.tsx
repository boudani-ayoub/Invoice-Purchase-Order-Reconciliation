"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  WORKFLOW_RESOLUTION_COPY,
  WORKFLOW_TEXT_LIMIT,
} from "@/constants/workflow";
import {
  commentFinding,
  manageFinding,
  transitionFinding,
  WorkflowRequestError,
} from "@/lib/api/workflow";
import type { Finding, WorkflowMutation } from "@/types/workflow";
import { AssigneePicker } from "./assignee-picker";

const utcInput = (value: string | null) =>
  value ? new Date(value).toISOString().slice(0, 16) : "";
const utcValue = (value: string) =>
  value ? new Date(`${value}Z`).toISOString() : null;

export function WorkflowControls({
  finding,
  onChanged,
  onComment,
}: {
  finding: Finding;
  onChanged: () => void;
  onComment: () => void;
}) {
  const auth = useAuth();
  const role = auth.session?.memberships.find(
    (m) => m.organization_id === auth.session?.active_organization_id,
  )?.role;
  const manager = role === "AP_MANAGER" || role === "ORG_ADMIN";
  const mayTransition =
    manager || finding.assignee_user_id === auth.session?.user.id;
  const [assignee, setAssignee] = useState(finding.assignee_user_id ?? "");
  const [due, setDue] = useState(utcInput(finding.due_at));
  const [reminder, setReminder] = useState(utcInput(finding.reminder_at));
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  const conflict =
    error instanceof WorkflowRequestError &&
    [0, 403, 404, 409].includes(error.status);
  const disabled = busy || conflict;
  async function perform(action: () => Promise<unknown>, isComment = false) {
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await action();
      if (isComment) {
        setComment("");
        setNotice("Comment added.");
        onComment();
      } else onChanged();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught
          : new Error("The workflow change could not be saved."),
      );
    } finally {
      setBusy(false);
    }
  }
  function saveSchedule() {
    const body: WorkflowMutation = { expected_version: finding.version };
    if (assignee !== (finding.assignee_user_id ?? ""))
      body.assignee_user_id = assignee || null;
    if (due !== utcInput(finding.due_at)) body.due_at = utcValue(due);
    if (reminder !== utcInput(finding.reminder_at))
      body.reminder_at = utcValue(reminder);
    return manageFinding(finding.id, body);
  }
  const changed =
    assignee !== (finding.assignee_user_id ?? "") ||
    due !== utcInput(finding.due_at) ||
    reminder !== utcInput(finding.reminder_at);
  return (
    <section
      aria-label="Workflow controls"
      className="space-y-6 rounded-lg border p-4 sm:p-5"
    >
      {error && (
        <div className="space-y-2">
          <p
            ref={errorRef}
            tabIndex={-1}
            role="alert"
            className="rounded-sm text-sm focus-visible:ring-2"
          >
            {error.message}
          </p>
          <Button
            variant="outline"
            onClick={() => {
              void auth.refresh();
              onChanged();
            }}
          >
            Refresh finding
          </Button>
        </div>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {manager && (
        <form
          aria-label="Assignment and schedule"
          className="max-w-2xl space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void perform(saveSchedule);
          }}
        >
          <h2 className="text-lg font-semibold">Assignment and schedule</h2>
          <AssigneePicker
            finding={finding}
            value={assignee}
            onChange={setAssignee}
            disabled={disabled}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block min-w-0 space-y-1 text-sm font-medium">
              Due date and time (UTC)
              <Input
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="block min-w-0 space-y-1 text-sm font-medium">
              Reminder date and time (UTC)
              <Input
                type="datetime-local"
                value={reminder}
                onChange={(e) => setReminder(e.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            Enter UTC times. Clear a date to remove it. Past dates are allowed.
          </p>
          <Button type="submit" disabled={disabled || !changed}>
            Save assignment and schedule
          </Button>
        </form>
      )}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Investigation status</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {WORKFLOW_RESOLUTION_COPY}
        </p>
        {!mayTransition && (
          <p className="text-sm">
            Only the assigned member or a manager can change this finding’s
            status.
          </p>
        )}
        {mayTransition && (
          <>
            {finding.status === "OPEN" && (
              <Button
                variant="outline"
                disabled={disabled}
                onClick={() =>
                  void perform(() =>
                    transitionFinding(finding.id, finding.version, "IN_REVIEW"),
                  )
                }
              >
                Start review
              </Button>
            )}
            {finding.status === "RESOLVED" ? (
              <Button
                variant="outline"
                disabled={disabled}
                onClick={() =>
                  void perform(() =>
                    transitionFinding(finding.id, finding.version, "OPEN"),
                  )
                }
              >
                Reopen finding
              </Button>
            ) : (
              <form
                aria-label="Resolve finding"
                className="max-w-2xl space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void perform(() =>
                    transitionFinding(
                      finding.id,
                      finding.version,
                      "RESOLVED",
                      note,
                    ),
                  );
                }}
              >
                <label className="block space-y-1 text-sm font-medium">
                  Resolution note
                  <textarea
                    className="block w-full rounded-md border bg-background p-3 font-normal focus-visible:ring-2"
                    rows={3}
                    value={note}
                    required
                    disabled={disabled}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                <p className="text-xs text-muted-foreground">
                  Required, persistent plain text. Maximum {WORKFLOW_TEXT_LIMIT}{" "}
                  Unicode characters.
                </p>
                <Button
                  type="submit"
                  disabled={
                    disabled ||
                    !note.trim() ||
                    [...note].length > WORKFLOW_TEXT_LIMIT
                  }
                >
                  Resolve finding
                </Button>
              </form>
            )}
          </>
        )}
      </div>
      <form
        aria-label="Add workflow comment"
        className="max-w-2xl space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void perform(() => commentFinding(finding.id, comment), true);
        }}
      >
        <h2 className="text-lg font-semibold">Add a comment</h2>
        <label className="block space-y-1 text-sm font-medium">
          Comment
          <textarea
            className="block w-full rounded-md border bg-background p-3 font-normal focus-visible:ring-2"
            rows={3}
            value={comment}
            required
            disabled={disabled}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <p className="text-xs text-muted-foreground">
          Visible to this organization. Comments are persistent and cannot be
          edited or deleted. Maximum {WORKFLOW_TEXT_LIMIT} Unicode characters.
        </p>
        <Button
          type="submit"
          disabled={
            disabled ||
            !comment.trim() ||
            [...comment].length > WORKFLOW_TEXT_LIMIT
          }
        >
          Add comment
        </Button>
      </form>
    </section>
  );
}
