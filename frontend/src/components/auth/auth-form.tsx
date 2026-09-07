"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ANALYSIS_HUB_PATH } from "@/constants/analysis-modes";
import {
  AUTH_ROUTES,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
} from "@/constants/auth";
import { authAction } from "@/lib/api/auth";
import type { AuthAction } from "@/types/auth";

type FormKind = "login" | "register" | "forgot" | "reset" | "verify";
const FORMS: Record<
  FormKind,
  { title: string; description: string; submit: string; action: AuthAction }
> = {
  login: {
    title: "Sign in",
    description: "Continue to your organization's procurement analyses.",
    submit: "Sign in",
    action: "login",
  },
  register: {
    title: "Create your account",
    description:
      "Set up your organization and start reviewing procurement records.",
    submit: "Create account",
    action: "register",
  },
  forgot: {
    title: "Forgot your password?",
    description: "Request a link to choose a new password.",
    submit: "Send recovery instructions",
    action: "forgot-password",
  },
  reset: {
    title: "Choose a new password",
    description: "This will sign out all existing sessions for your account.",
    submit: "Change password",
    action: "reset-password",
  },
  verify: {
    title: "Verify your email",
    description:
      "Confirm your email before signing in, or request a fresh verification link.",
    submit: "Verify email",
    action: "verify-email",
  },
};

const subscribeToHydration = () => () => {};

export function AuthForm({ kind }: { kind: FormKind }) {
  const hydrated = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );
  return hydrated ? (
    <AccountForm key={kind} kind={kind} />
  ) : (
    <main className="mx-auto p-8" role="status">
      Opening account form…
    </main>
  );
}

function AccountForm({ kind }: { kind: FormKind }) {
  const definition = FORMS[kind];
  const router = useRouter();
  const auth = useAuth();
  const [token, setToken] = useState(() =>
    kind === "reset" || kind === "verify"
      ? (new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "")
      : "",
  );
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const feedback = useRef<HTMLParagraphElement>(null);
  const withPassword = ["login", "register", "reset"].includes(kind);
  const withEmail =
    ["login", "register", "forgot"].includes(kind) ||
    (kind === "verify" && !token);

  useEffect(() => {
    if (kind !== "reset" && kind !== "verify") return;
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
  }, [kind]);

  useEffect(() => {
    if (error || message) feedback.current?.focus();
  }, [error, message]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const body: Record<string, string> = {};
    for (const name of [
      "email",
      "password",
      "display_name",
      "organization_name",
    ]) {
      const value = form.get(name);
      if (typeof value === "string") body[name] = value;
    }
    if (token) body.token = token;
    if (
      withPassword &&
      kind !== "login" &&
      (Array.from(body.password).length < PASSWORD_MIN_LENGTH ||
        Array.from(body.password).length > PASSWORD_MAX_LENGTH)
    ) {
      setError(
        `Use ${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} characters. Spaces and Unicode are welcome.`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const action =
        kind === "verify" && !token ? "resend-verification" : definition.action;
      const result = await authAction(action, body);
      if (kind === "login") {
        await auth.refresh();
        router.replace(ANALYSIS_HUB_PATH);
      } else {
        setMessage(result ?? "Your request was completed.");
        if (kind === "reset" || kind === "verify") setToken("");
      }
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Unable to complete this request.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-5 py-12">
      <p className="mb-8 text-sm font-semibold text-primary">
        Procurement analysis
      </p>
      <h1 className="text-2xl font-semibold tracking-tight">
        {definition.title}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {definition.description}
      </p>
      <form onSubmit={submit} className="mt-7 space-y-5">
        {kind === "register" && (
          <>
            <div className="space-y-2">
              <Label htmlFor="display-name">Your name</Label>
              <Input
                id="display-name"
                name="display_name"
                autoComplete="name"
                maxLength={200}
                required
                disabled={busy}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="organization-name">Organization name</Label>
              <Input
                id="organization-name"
                name="organization_name"
                autoComplete="organization"
                maxLength={200}
                required
                disabled={busy}
              />
            </div>
          </>
        )}
        {withEmail && (
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              maxLength={254}
              required
              disabled={busy}
            />
          </div>
        )}
        {withPassword && (
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <div className="flex gap-2">
              <Input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete={
                  kind === "login" ? "current-password" : "new-password"
                }
                maxLength={256}
                required
                disabled={busy}
                aria-describedby={
                  kind === "login" ? undefined : "password-guidance"
                }
              />
              <Button
                type="button"
                variant="outline"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? "Hide" : "Show"}
              </Button>
            </div>
            {kind !== "login" && (
              <p
                id="password-guidance"
                className="text-xs text-muted-foreground"
              >
                Use {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} characters.
                Spaces and Unicode are welcome. No required symbols or uppercase
                letters.
              </p>
            )}
          </div>
        )}
        {kind === "reset" && !token && !message && (
          <p className="text-sm text-muted-foreground">
            Open the link from your recovery email. If it has expired, request a
            new one below.
          </p>
        )}
        {error && (
          <p
            ref={feedback}
            tabIndex={-1}
            role="alert"
            className="rounded-md border border-destructive/40 p-3 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        {message && (
          <p
            ref={feedback}
            tabIndex={-1}
            role="status"
            className="rounded-md border p-3 text-sm"
          >
            {message}
          </p>
        )}
        <Button
          type="submit"
          className="w-full"
          disabled={busy || (kind === "reset" && !token)}
        >
          {busy
            ? "Please wait…"
            : kind === "verify" && !token
              ? "Resend verification"
              : definition.submit}
        </Button>
      </form>
      <nav
        aria-label="Account links"
        className="mt-6 flex flex-wrap gap-x-5 gap-y-3 text-sm"
      >
        {kind === "verify" && token && (
          <button
            type="button"
            onClick={() => setToken("")}
            className="text-primary underline underline-offset-4"
          >
            Request a new verification link
          </button>
        )}
        {kind !== "login" && (
          <Link
            href={AUTH_ROUTES.login}
            className="text-primary underline underline-offset-4"
          >
            Sign in
          </Link>
        )}
        {kind === "login" && (
          <Link
            href={AUTH_ROUTES.register}
            className="text-primary underline underline-offset-4"
          >
            Create account
          </Link>
        )}
        {(kind === "login" || kind === "reset") && (
          <Link
            href={AUTH_ROUTES.forgot}
            className="text-primary underline underline-offset-4"
          >
            Forgot password
          </Link>
        )}
        {(kind === "login" || kind === "register") && (
          <Link
            href={AUTH_ROUTES.verify}
            className="text-primary underline underline-offset-4"
          >
            Verify email
          </Link>
        )}
      </nav>
    </main>
  );
}
