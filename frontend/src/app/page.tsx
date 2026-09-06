import { FileCheck2 } from "lucide-react";
import Link from "next/link";
import { ANALYSIS_HUB_PATH } from "@/constants/analysis-modes";

import { ReconciliationWorkspace } from "@/components/reconciliation/reconciliation-workspace";

export default function Home() {
  return (
    <>
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-5 sm:px-6 lg:px-8">
          <div className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <FileCheck2 aria-hidden="true" className="size-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              Reconciliation
            </h1>
            <p className="text-sm text-muted-foreground">
              Invoice · Purchase order · Goods receipt matching
            </p>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
        <Link
          href={ANALYSIS_HUB_PATH}
          className="mb-6 inline-block font-medium text-primary underline underline-offset-4"
        >
          Choose an analysis workflow
        </Link>
        <ReconciliationWorkspace />
      </main>
      <footer className="border-t bg-card">
        <div className="mx-auto max-w-7xl px-4 py-4 text-xs text-muted-foreground sm:px-6 lg:px-8">
          Deterministic reconciliation. Results reflect the uploaded source
          files.
        </div>
      </footer>
    </>
  );
}
