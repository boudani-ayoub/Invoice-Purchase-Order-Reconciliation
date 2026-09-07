"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ANALYSIS_HUB_PATH } from "@/constants/analysis-modes";
import { AUTH_ROUTES } from "@/constants/auth";

export function ProtectedApp({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!auth.loading && !auth.error && !auth.session)
      router.replace(AUTH_ROUTES.login);
  }, [auth.loading, auth.error, auth.session, router]);

  if (auth.loading)
    return (
      <main className="mx-auto p-8" role="status">
        Checking your session…
      </main>
    );
  if (auth.error)
    return (
      <main className="mx-auto space-y-4 p-8">
        <p role="alert">{auth.error}</p>
        <Button onClick={() => void auth.refresh()}>Try again</Button>
      </main>
    );
  if (!auth.session)
    return (
      <main className="mx-auto p-8" role="status">
        Opening sign in…
      </main>
    );

  const session = auth.session;
  const active = session.memberships.find(
    (m) => m.organization_id === session.active_organization_id,
  );
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "The action could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="border-b bg-card">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6"
        >
          <Link
            href={ANALYSIS_HUB_PATH}
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            Reconcile
          </Link>
          <div className="flex min-w-0 flex-wrap items-center gap-4">
            {session.memberships.length > 1 ? (
              <div className="space-y-1">
                <Label htmlFor="active-organization">Organization</Label>
                <select
                  id="active-organization"
                  className="block w-full max-w-xs rounded-md border bg-background p-2 text-sm"
                  value={active?.organization_id ?? ""}
                  disabled={busy}
                  onChange={(event) =>
                    void act(() => auth.selectOrganization(event.target.value))
                  }
                >
                  <option value="" disabled>
                    Select an organization
                  </option>
                  {session.memberships.map((m) => (
                    <option key={m.organization_id} value={m.organization_id}>
                      {m.organization_name}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <p className="max-w-xs break-words text-sm font-medium">
                {active?.organization_name ?? "No active organization"}
              </p>
            )}
            <span className="max-w-xs break-words text-sm text-muted-foreground">
              {session.user.display_name}
            </span>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void act(auth.logout)}
            >
              Sign out
            </Button>
          </div>
        </nav>
      </header>
      {error && (
        <p role="alert" className="mx-auto px-4 pt-4 text-destructive">
          {error}
        </p>
      )}
      {active ? (
        <div key={active.organization_id} className="flex flex-1 flex-col">
          {children}
        </div>
      ) : (
        <main className="mx-auto p-8">
          <h1 className="text-xl font-semibold">Choose your organization</h1>
          <p className="mt-2 text-muted-foreground">
            {session.memberships.length
              ? "Select an active organization to run an analysis."
              : "Your account has no active organization membership. Contact your organization administrator."}
          </p>
        </main>
      )}
    </>
  );
}
