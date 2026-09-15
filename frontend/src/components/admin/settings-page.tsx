"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AdminRequestError,
  getOrganization,
  renameOrganization,
} from "@/lib/api/admin";
import type { OrganizationSettings } from "@/types/admin";

const GOVERNANCE_FACTS = [
  "Raw uploaded CSV bytes are temporary and are not retained after processing.",
  "Validated source records and immutable result snapshots are persisted.",
  "Workflow comments and resolution notes are persisted in their workflow context.",
  "Archive is reversible hiding, not deletion.",
  "Run audit, workflow, and governance events are retained.",
  "There is currently no automatic retention or purge engine.",
  "Backups may retain archived data beyond the live database lifecycle.",
] as const;

export function SettingsPage() {
  const [organization, setOrganization] = useState<OrganizationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const feedback = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setConflict(false);
    try {
      setOrganization(await getOrganization());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Settings could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const pending = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(pending);
  }, [refresh]);
  useEffect(() => {
    if (error || message) feedback.current?.focus();
  }, [error, message]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!organization || busy) return;
    const name = String(new FormData(event.currentTarget).get("name") ?? "");
    setBusy(true);
    setError(null);
    setMessage(null);
    setConflict(false);
    try {
      setOrganization(await renameOrganization(organization.version, name));
      setMessage("Organization name updated.");
    } catch (caught) {
      setConflict(caught instanceof AdminRequestError && caught.status === 409);
      setError(caught instanceof Error ? caught.message : "The name could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-10">
      <section className="space-y-5" aria-labelledby="settings-title">
        <div>
          <h1 id="settings-title" className="text-2xl font-semibold">
            Organization settings
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Update the company display name. The internal organization slug is
            not editable.
          </p>
        </div>
        {(error || message) && (
          <div
            ref={feedback}
            tabIndex={-1}
            role={error ? "alert" : "status"}
            className={`flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm ${
              error ? "border-destructive/40 text-destructive" : "text-foreground"
            }`}
          >
            <span>{error ?? message}</span>
            {conflict && (
              <Button type="button" variant="outline" onClick={() => void refresh()}>
                Refresh
              </Button>
            )}
          </div>
        )}
        {loading ? (
          <p role="status">Loading organization settings…</p>
        ) : organization ? (
          <form onSubmit={submit} className="max-w-xl space-y-4 rounded-lg border bg-card p-4">
            <div className="space-y-2">
              <Label htmlFor="organization-name">Display name</Label>
              <Input
                id="organization-name"
                name="name"
                defaultValue={organization.name}
                key={`${organization.id}:${organization.version}`}
                maxLength={200}
                required
                disabled={busy}
              />
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save name"}
            </Button>
          </form>
        ) : null}
      </section>

      <section aria-labelledby="governance-title">
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 id="governance-title">Current data governance</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="list-disc space-y-2 pl-5 text-sm">
              {GOVERNANCE_FACTS.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
            <p className="text-sm text-muted-foreground">
              These statements describe current product behavior; they are not
              a certification or regulatory compliance claim. Permanent purge
              and legal-hold controls are not available.
            </p>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
