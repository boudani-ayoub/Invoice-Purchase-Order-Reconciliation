import { ProtectedApp } from "@/components/auth/protected-app";

export default function AnalysisLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedApp>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
      <footer className="border-t px-4 py-4 text-center text-xs text-muted-foreground">
        Results reflect the uploaded source files. Uploads and reports are not
        stored.
      </footer>
    </ProtectedApp>
  );
}
