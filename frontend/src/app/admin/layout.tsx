import { AdminShell } from "@/components/admin/admin-shell";
import { ProtectedApp } from "@/components/auth/protected-app";

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <ProtectedApp>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <AdminShell>{children}</AdminShell>
      </main>
    </ProtectedApp>
  );
}
