"use client";

import { useId } from "react";
import { ACTIVITY_SERIES } from "@/constants/dashboard";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DashboardTrends } from "@/types/dashboard";

export function ActivityTrend({ trends }: { trends: DashboardTrends }) {
  const id = useId();
  const width = 720,
    height = 220,
    left = 44,
    right = 12,
    top = 16,
    bottom = 30;
  const max = Math.max(
    1,
    ...trends.items.flatMap((row) =>
      ACTIVITY_SERIES.map((series) => row[series.key]),
    ),
  );
  const x = (i: number) =>
    left + (i * (width - left - right)) / Math.max(1, trends.items.length - 1);
  const y = (value: number) =>
    top + (1 - value / max) * (height - top - bottom);
  const active = trends.items.some((row) =>
    ACTIVITY_SERIES.some((series) => row[series.key] > 0),
  );
  return (
    <div className="space-y-4">
      {active ? (
        <>
          <svg
            role="img"
            aria-labelledby={`${id}-title ${id}-desc`}
            viewBox={`0 0 ${width} ${height}`}
            className="w-full max-w-4xl overflow-visible"
          >
            <title id={`${id}-title`}>Daily workflow activity, UTC</title>
            <desc id={`${id}-desc`}>
              New findings, resolution actions and reopen actions. Solid, dashed
              and dotted lines. Exact values are in the daily activity table
              below.
            </desc>
            {[...new Set([0, Math.ceil(max / 2), max])].map((value) => (
              <g key={value}>
                <line
                  x1={left}
                  y1={y(value)}
                  x2={width - right}
                  y2={y(value)}
                  className="stroke-border"
                />
                <text
                  x={left - 8}
                  y={y(value) + 4}
                  textAnchor="end"
                  fill="currentColor"
                  className="text-[24px] sm:text-[12px]"
                >
                  {value}
                </text>
              </g>
            ))}
            {ACTIVITY_SERIES.map((series) => (
              <polyline
                key={series.key}
                points={trends.items
                  .map((row, i) => `${x(i)},${y(row[series.key])}`)
                  .join(" ")}
                fill="none"
                stroke="currentColor"
                strokeWidth={2.5}
                strokeDasharray={series.dash}
                className={series.className}
              />
            ))}
            <text
              x={left}
              y={height - 5}
              fill="currentColor"
              className="text-[24px] sm:text-[12px]"
            >
              {trends.items[0]?.bucket_start.slice(0, 10)}
            </text>
            <text
              x={width - right}
              y={height - 5}
              textAnchor="end"
              fill="currentColor"
              className="text-[24px] sm:text-[12px]"
            >
              {trends.items.at(-1)?.bucket_start.slice(0, 10)}
            </text>
          </svg>
          <ul
            aria-label="Trend legend"
            className="flex flex-wrap gap-x-5 gap-y-2 text-sm"
          >
            {ACTIVITY_SERIES.map((series) => (
              <li key={series.key} className="flex items-center gap-2">
                <svg
                  aria-hidden="true"
                  width="28"
                  height="8"
                  className={series.className}
                >
                  <line
                    x1="0"
                    y1="4"
                    x2="28"
                    y2="4"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeDasharray={series.dash}
                  />
                </svg>
                {series.label}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          No finding creation, resolution or reopen activity in this period.
        </p>
      )}
      <details className="rounded-md border p-3">
        <summary className="cursor-pointer text-sm font-medium">
          Daily activity table
        </summary>
        <div className="mt-3 max-h-80 overflow-y-auto">
          <Table
            aria-label="Daily workflow activity"
            scrollLabel="Daily activity table scroll area"
          >
            <TableHeader>
              <TableRow>
                <TableHead scope="col">UTC date</TableHead>
                {ACTIVITY_SERIES.map((s) => (
                  <TableHead key={s.key} scope="col">
                    {s.label}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {trends.items.map((row) => (
                <TableRow key={row.bucket_start}>
                  <TableHead scope="row">
                    {row.bucket_start.slice(0, 10)}
                  </TableHead>
                  {ACTIVITY_SERIES.map((s) => (
                    <TableCell key={s.key} className="tabular-nums">
                      {row[s.key]}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </details>
    </div>
  );
}
