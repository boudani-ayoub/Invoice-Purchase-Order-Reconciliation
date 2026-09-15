import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ADMIN_PATH } from "@/constants/admin";

const SECTIONS = [
  {
    href: `${ADMIN_PATH}/members`,
    title: "Members & invitations",
    description:
      "Manage company memberships, roles, access status, and pending invitations.",
  },
  {
    href: `${ADMIN_PATH}/settings`,
    title: "Organization settings",
    description:
      "Update the organization display name and review data-governance boundaries.",
  },
  {
    href: `${ADMIN_PATH}/audit`,
    title: "Organization audit",
    description:
      "Review retained run, workflow, and governance activity in one timeline.",
  },
] as const;

export function AdminOverview() {
  return (
    <section className="space-y-6" aria-labelledby="admin-title">
      <div>
        <p className="text-sm font-semibold text-primary">Organization</p>
        <h1 id="admin-title" className="mt-1 text-2xl font-semibold">
          Administration
        </h1>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          Govern the active organization. This area does not provide platform
          administration or access to other organizations.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {SECTIONS.map((section) => (
          <Card key={section.href}>
            <CardHeader>
              <CardTitle>
                <Link
                  href={section.href}
                  className="text-primary underline underline-offset-4"
                >
                  {section.title}
                </Link>
              </CardTitle>
              <CardDescription>{section.description}</CardDescription>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">
              Changes are authorized against current server-side membership.
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
