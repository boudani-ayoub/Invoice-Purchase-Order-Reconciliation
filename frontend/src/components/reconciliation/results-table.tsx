"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getIssuePresentation, STATUS_PRESENTATION } from "@/constants/issues";
import { formatDecimalString } from "@/lib/formatters";
import type { ReconciliationResult } from "@/types/reconciliation";

type StatusFilter = "all" | "review" | "matched";

interface ResultsTableProps {
  results: ReconciliationResult[];
}

export function ResultsTable({ results }: ResultsTableProps) {
  const hasReviewItems = results.some((result) => result.status === "REVIEW_REQUIRED");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(
    hasReviewItems ? "review" : "all",
  );
  const [issueFilter, setIssueFilter] = useState("all");
  const [search, setSearch] = useState("");

  const issueOptions = useMemo(
    () =>
      [...new Set(results.flatMap((result) => result.issues))].sort((left, right) =>
        getIssuePresentation(left).label.localeCompare(getIssuePresentation(right).label),
      ),
    [results],
  );

  const filteredResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    return results.filter((result) => {
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "review" && result.status === "REVIEW_REQUIRED") ||
        (statusFilter === "matched" && result.status === "MATCHED");
      const matchesIssue = issueFilter === "all" || result.issues.includes(issueFilter);
      const matchesSearch =
        !query ||
        [result.invoice_number, result.po_number, result.supplier_id, result.item_code].some(
          (value) => value.toLowerCase().includes(query),
        );
      return matchesStatus && matchesIssue && matchesSearch;
    });
  }, [issueFilter, results, search, statusFilter]);

  return (
    <section aria-labelledby="result-lines-heading" className="space-y-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h3 id="result-lines-heading" className="text-lg font-semibold">
            Reconciliation lines
          </h3>
          <p className="mt-1 text-sm text-muted-foreground" aria-live="polite">
            Showing {filteredResults.length} of {results.length} lines
          </p>
        </div>

        <div className="flex flex-col gap-2 md:flex-row md:items-center">
          <div className="inline-flex w-fit rounded-lg border bg-card p-1" aria-label="Status filter">
            {(
              [
                ["all", "All"],
                ["review", "Review required"],
                ["matched", "Matched"],
              ] as const
            ).map(([value, label]) => (
              <Button
                key={value}
                type="button"
                size="sm"
                variant={statusFilter === value ? "secondary" : "ghost"}
                aria-pressed={statusFilter === value}
                onClick={() => setStatusFilter(value)}
              >
                {label}
              </Button>
            ))}
          </div>

          <Select value={issueFilter} onValueChange={(value) => setIssueFilter(value ?? "all")}>
            <SelectTrigger aria-label="Filter by issue" className="w-full md:w-52">
              <SelectValue placeholder="All issues" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All issues</SelectItem>
              {issueOptions.map((code) => (
                <SelectItem key={code} value={code}>
                  {getIssuePresentation(code).label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="relative md:w-64">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <label htmlFor="result-search" className="sr-only">
              Search reconciliation lines
            </label>
            <input
              id="result-search"
              type="search"
              value={search}
              placeholder="Search invoice, PO, supplier…"
              className="h-8 w-full rounded-lg border bg-background pr-3 pl-9 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="rounded-xl border bg-card">
        <Table>
          <TableCaption className="sr-only">Filtered reconciliation result lines.</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Invoice</TableHead>
              <TableHead>Supplier</TableHead>
              <TableHead>Purchase order</TableHead>
              <TableHead>Item</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Issues</TableHead>
              <TableHead className="text-right">Invoice / supported qty</TableHead>
              <TableHead className="text-right">Invoice / PO price</TableHead>
              <TableHead className="text-right">Potential dispute</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredResults.length ? (
              filteredResults.map((result, index) => {
                const status = STATUS_PRESENTATION[result.status];
                return (
                  <TableRow key={`${result.invoice_number}-${result.invoice_line_number}-${index}`}>
                    <TableCell>
                      <span className="font-medium">{result.invoice_number}</span>
                      <span className="block text-xs text-muted-foreground">
                        Line {result.invoice_line_number}
                      </span>
                    </TableCell>
                    <TableCell>{result.supplier_id}</TableCell>
                    <TableCell>
                      {result.po_number}
                      <span className="block text-xs text-muted-foreground">
                        Line {result.po_line_number}
                      </span>
                    </TableCell>
                    <TableCell>{result.item_code}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={status.className}>
                        {status.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-72 whitespace-normal">
                      {result.issues.length ? (
                        <div className="flex flex-wrap gap-1">
                          {result.issues.map((code) => {
                            const issue = getIssuePresentation(code);
                            return (
                              <Badge
                                key={code}
                                variant={issue.tone === "destructive" ? "destructive" : "secondary"}
                                title={issue.description}
                              >
                                {issue.label}
                              </Badge>
                            );
                          })}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">None</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatDecimalString(result.current_invoiced_quantity)} /{" "}
                      {result.supported_quantity === null
                        ? "—"
                        : formatDecimalString(result.supported_quantity)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatDecimalString(result.invoice_unit_price)} /{" "}
                      {result.po_unit_price === null
                        ? "—"
                        : formatDecimalString(result.po_unit_price)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm font-medium tabular-nums">
                      {formatDecimalString(result.potential_disputed_amount)} {result.currency}
                    </TableCell>
                  </TableRow>
                );
              })
            ) : (
              <TableRow>
                <TableCell colSpan={9} className="h-24 text-center text-muted-foreground">
                  No lines match the current filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
