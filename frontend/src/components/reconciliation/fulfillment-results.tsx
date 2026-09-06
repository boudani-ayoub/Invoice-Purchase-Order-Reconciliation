import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DisputedAmounts } from "./disputed-amounts";
import { FULFILLMENT_LABELS } from "@/constants/analysis-modes";
import { getIssuePresentation } from "@/constants/issues";
import { formatDecimalString } from "@/lib/formatters";
import type { PoReceiptReport } from "@/types/analysis";

export function FulfillmentResults({ report }: { report: PoReceiptReport }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(FULFILLMENT_LABELS).map(([status, label]) => (
          <Card key={status} className="shadow-none">
            <CardContent>
              <p className="text-sm text-muted-foreground">{label}</p>
              <p className="mt-1 text-2xl font-semibold">
                {
                  report.summary.status_counts[
                    status as keyof typeof FULFILLMENT_LABELS
                  ]
                }
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {report.summary.po_lines_processed} order lines ·{" "}
        {report.summary.receipt_lines_processed} receipt lines ·{" "}
        {report.summary.orphan_receipt_lines} unresolved receipt lines
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <DisputedAmounts
          title="Outstanding ordered value"
          emptyMessage="No outstanding ordered value."
          amounts={report.summary.outstanding_values}
        />
        <DisputedAmounts
          title="Over-received reference value"
          emptyMessage="No over-received value."
          amounts={report.summary.over_received_values}
        />
      </div>
      <div className="rounded-xl border bg-card">
        <Table scrollLabel="Fulfillment quantities">
          <TableCaption>
            Ordered and received quantities. Open deliveries may still be in
            progress.
          </TableCaption>
          <TableHeader>
            <TableRow>
              {[
                "Purchase order",
                "Item",
                "Supplier",
                "Fulfillment",
                "Ordered",
                "Received",
                "Outstanding",
                "Over-received",
              ].map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.results.map((row) => (
              <TableRow key={`${row.po_number}/${row.po_line_number}`}>
                <TableCell>
                  {row.po_number} / {row.po_line_number}
                </TableCell>
                <TableCell>{row.item_code}</TableCell>
                <TableCell>{row.supplier_id}</TableCell>
                <TableCell>{FULFILLMENT_LABELS[row.status]}</TableCell>
                {[
                  row.ordered_quantity,
                  row.received_quantity,
                  row.outstanding_quantity,
                  row.over_received_quantity,
                ].map((value, index) => (
                  <TableCell className="font-mono tabular-nums" key={index}>
                    {formatDecimalString(value)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <section aria-labelledby="orphan-heading" className="space-y-3">
        <h3 id="orphan-heading" className="text-lg font-semibold">
          Unresolved receipts
        </h3>
        {report.orphan_receipts.length ? (
          <div className="rounded-xl border bg-card">
            <Table scrollLabel="Unresolved receipt lines">
              <TableCaption>
                Receipts excluded from ordered-line totals because their
                references could not be resolved.
              </TableCaption>
              <TableHeader>
                <TableRow>
                  {[
                    "Receipt",
                    "PO reference",
                    "Item",
                    "Quantity",
                    "Finding",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.orphan_receipts.map((row) => (
                  <TableRow
                    key={`${row.receipt_id}/${row.receipt_line_number}`}
                  >
                    <TableCell>
                      {row.receipt_id} / {row.receipt_line_number}
                    </TableCell>
                    <TableCell>
                      {row.po_number} / {row.po_line_number}
                    </TableCell>
                    <TableCell>{row.item_code}</TableCell>
                    <TableCell>
                      {formatDecimalString(row.received_quantity)}
                    </TableCell>
                    <TableCell>
                      {getIssuePresentation(row.issue).label}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            All receipts resolve to a provided order line and item.
          </p>
        )}
      </section>
    </div>
  );
}
