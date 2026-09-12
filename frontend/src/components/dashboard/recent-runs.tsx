import Link from "next/link";
import { RunDate, RunSummary } from "@/components/history/run-summary";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { HISTORY_PATH, runPath } from "@/constants/runs";
import { formatDecimalString } from "@/lib/formatters";
import type { RunListItem } from "@/types/runs";

export function RecentRuns({ runs }: { runs: RunListItem[] }) {
  return (
    <section aria-labelledby="recent-title" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="recent-title" className="text-xl font-semibold">
          Recent analyses
        </h2>
        <Link href={HISTORY_PATH} className="text-sm text-primary underline">
          View History
        </Link>
      </div>
      <p className="max-w-4xl text-sm text-muted-foreground">
        Latest non-archived saved runs, independent of the activity window.
        Amounts belong to each run only. Repeated or overlapping analyses must
        not be added together as business exposure.
      </p>
      {!runs.length ? (
        <p className="rounded-md border p-4 text-sm">
          No non-archived analyses yet. Saved runs will appear here.
        </p>
      ) : (
        <ul className="divide-y rounded-md border bg-card">
          {runs.map((run) => {
            const summary = run.summary;
            const amounts: Array<[string, Record<string, string>]> =
              "disputed_amounts" in summary
                ? [
                    [
                      "Potential disputed amount — this run",
                      summary.disputed_amounts,
                    ],
                  ]
                : "unsupported_amounts" in summary
                  ? [
                      [
                        "Potential unsupported invoice amount — this run",
                        summary.unsupported_amounts,
                      ],
                    ]
                  : [
                      [
                        "Outstanding ordered value — this run",
                        summary.outstanding_values,
                      ],
                      [
                        "Over-received reference value — this run",
                        summary.over_received_values,
                      ],
                    ];
            return (
              <li key={run.id} className="min-w-0 space-y-3 p-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <Link
                    prefetch={false}
                    href={runPath(run.id)}
                    className="min-w-0 break-words font-semibold text-primary underline"
                  >
                    {run.title ?? ANALYSIS_MODES[run.mode].title}
                  </Link>
                  <span className="text-sm">
                    Completed · <RunDate value={run.created_at} />
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {ANALYSIS_MODES[run.mode].title}
                </p>
                <RunSummary run={run} />
                {amounts.map(([label, values]) => (
                  <div key={label} className="space-y-1">
                    <h3 className="text-sm font-medium">{label}</h3>
                    {Object.keys(values).length ? (
                      <dl className="flex flex-wrap gap-x-6 gap-y-2">
                        {Object.entries(values).map(([currency, amount]) => (
                          <div key={currency} className="flex gap-2 text-sm">
                            <dt>{currency}</dt>
                            <dd className="font-mono tabular-nums">
                              {formatDecimalString(amount)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No amounts in this summary.
                      </p>
                    )}
                  </div>
                ))}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
