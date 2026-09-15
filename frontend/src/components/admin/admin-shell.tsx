"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { ADMIN_PATH, canViewAdmin } from "@/constants/admin";

const LINKS = [
  [ADMIN_PATH, "Overview"],
  [`${ADMIN_PATH}/members`, "Members & invitations"],
  [`${ADMIN_PATH}/settings`, "Settings"],
  [`${ADMIN_PATH}/audit`, "Audit"],
] as const;

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { session } = useAuth();
  const active = session?.memberships.find(
    (membership) =>
      membership.organization_id === session.active_organization_id,
  );

  if (!canViewAdmin(active?.role)) {
    return (
      <section className="space-y-3" aria-labelledby="admin-denied-title">
        <h1 id="admin-denied-title" className="text-2xl font-semibold">
          Admin access required
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Organization administration is available only to an active
          organization administrator. The server checks every administration
          request independently.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-8">
      <nav
        aria-label="Administration navigation"
        className="flex flex-wrap gap-x-5 gap-y-3 border-b pb-4 text-sm"
      >
        {LINKS.map(([href, label]) => (
          <Link
            key={href}
            href={href}
            aria-current={pathname === href ? "page" : undefined}
            className="font-medium text-primary underline-offset-4 hover:underline aria-[current=page]:underline"
          >
            {label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
