import Link from "next/link";
import { ANALYSIS_HUB_PATH } from "@/constants/analysis-modes";

export default function AnalysisLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <header className="border-b bg-card">
        <nav
          aria-label="Main navigation"
          className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8"
        >
          <Link
            className="font-semibold text-primary underline-offset-4 hover:underline"
            href={ANALYSIS_HUB_PATH}
          >
            Reconcile
          </Link>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
      <footer className="border-t px-4 py-4 text-center text-xs text-muted-foreground">
        Results reflect the uploaded source files. Uploads and reports are not
        stored.
      </footer>
    </>
  );
}
