"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ADMIN_PATH } from "@/constants/admin";
import {
  AUTH_ROUTES,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
} from "@/constants/auth";
import {
  acceptInvitation,
  previewInvitation,
  registerInvited,
} from "@/lib/api/admin";
import type { InvitationPreview } from "@/types/admin";

const subscribeToHydration = () => () => {};

export function InvitationPage() {
  const hydrated = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
  return hydrated ? <InvitationClient /> : <main className="mx-auto p-8">Opening invitation…</main>;
}

function InvitationClient() {
  const auth = useAuth();
  const [token, setToken] = useState(
    () => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "",
  );
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [busy, setBusy] = useState(Boolean(token));
  const [error, setError] = useState<string | null>(() =>
    token ? null : "Open the invitation link from your email.",
  );
  const [message, setMessage] = useState<string | null>(null);
  const feedback = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    if (!token) return;
    let active = true;
    void previewInvitation(token).then(
      (value) => {
        if (active) setPreview(value);
      },
      (caught) => {
        if (active)
          setError(caught instanceof Error ? caught.message : "This invitation is unavailable.");
      },
    ).finally(() => {
      if (active) setBusy(false);
    });
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (error || message) feedback.current?.focus();
  }, [error, message]);

  async function accept() {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await acceptInvitation(token);
      setToken("");
      setMessage("Invitation accepted. Choose the organization from the account menu.");
      await auth.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The invitation could not be accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function register(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || busy) return;
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    if (
      Array.from(password).length < PASSWORD_MIN_LENGTH ||
      Array.from(password).length > PASSWORD_MAX_LENGTH
    ) {
      setError(`Use ${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} password characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerInvited(token, String(data.get("display_name") ?? ""), password);
      setToken("");
      setMessage("Account created. Sign in to choose your organization.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The account could not be created.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center px-5 py-12">
      <p className="text-sm font-semibold text-primary">Organization invitation</p>
      <h1 className="mt-2 text-2xl font-semibold">Join your team</h1>
      {preview && (
        <div className="mt-5 space-y-2 rounded-lg border bg-card p-4 text-sm">
          <p className="font-semibold break-words">{preview.organization_name}</p>
          <p className="break-all">{preview.email}</p>
          <p>Role: {preview.role.toLowerCase().replace("_", " ")}</p>
          <p className="text-muted-foreground">
            Expires {new Date(preview.expires_at).toLocaleString()}
          </p>
        </div>
      )}
      {(error || message) && (
        <p
          ref={feedback}
          tabIndex={-1}
          role={error ? "alert" : "status"}
          className={`mt-5 rounded-md border p-3 text-sm ${error ? "border-destructive/40 text-destructive" : ""}`}
        >
          {error ?? message}
        </p>
      )}
      {busy && !preview ? <p className="mt-5" role="status">Checking invitation…</p> : null}
      {preview && !message && !auth.loading && auth.session ? (
        <div className="mt-6 space-y-3">
          <p className="text-sm">
            Signed in as <span className="font-medium break-all">{auth.session.user.email}</span>
          </p>
          <Button className="w-full" onClick={() => void accept()} disabled={busy}>
            {busy ? "Accepting…" : "Accept invitation"}
          </Button>
        </div>
      ) : null}
      {preview && !message && !auth.loading && !auth.session ? (
        <form onSubmit={register} className="mt-6 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="invited-display-name">Your name</Label>
            <Input id="invited-display-name" name="display_name" autoComplete="name" maxLength={200} required disabled={busy} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invited-password">Password</Label>
            <Input id="invited-password" name="password" type="password" autoComplete="new-password" maxLength={256} required disabled={busy} />
            <p className="text-xs text-muted-foreground">
              Use {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} characters.
            </p>
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Creating account…" : "Create invited account"}
          </Button>
        </form>
      ) : null}
      <nav aria-label="Invitation links" className="mt-6 flex flex-wrap gap-4 text-sm">
        <Link href={AUTH_ROUTES.login} className="text-primary underline underline-offset-4">
          Sign in
        </Link>
        {auth.session?.memberships.some((membership) => membership.role === "ORG_ADMIN") && (
          <Link href={ADMIN_PATH} className="text-primary underline underline-offset-4">
            Open administration
          </Link>
        )}
      </nav>
    </main>
  );
}
