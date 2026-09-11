import { ProtectedApp } from "@/components/auth/protected-app";

export default function WorkLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedApp>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
    </ProtectedApp>
  );
}
