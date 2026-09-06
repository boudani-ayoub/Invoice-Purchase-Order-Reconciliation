import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ANALYSIS_MODES, analysisPath } from "@/constants/analysis-modes";

export function AnalysisHub() {
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Choose what you want to compare
        </h1>
        <p className="mt-2 text-muted-foreground">
          Start with the exports you have and the question you need to answer.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {Object.values(ANALYSIS_MODES).map((mode) => (
          <Link
            key={mode.id}
            href={analysisPath(mode.id)}
            className="block rounded-xl border bg-card p-6 transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
          >
            <h2 className="flex items-center justify-between gap-4 text-lg font-semibold">
              {mode.title}
              <ArrowRight aria-hidden="true" className="size-5 shrink-0" />
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {mode.description}
            </p>
            <p className="mt-4 text-sm font-medium">{mode.question}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}
