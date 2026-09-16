"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { RunDate } from "@/components/history/run-summary";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  canViewInsights,
  INTELLIGENCE_WINDOWS,
  RUN_SELECTOR_LIMIT,
} from "@/constants/intelligence";
import { useRunResource } from "@/hooks/use-run-resource";
import {
  getInventoryIntelligence,
  getProcurementIntelligence,
  getSupplierIntelligence,
} from "@/lib/api/intelligence";
import { listRuns } from "@/lib/api/runs";
import { formatDecimalString } from "@/lib/formatters";
import type {
  CountMap,
  IntelligenceWindow,
  InventoryIntelligence,
  MoneyMap,
  ProcurementIntelligence,
  SupplierIntelligence,
  SupplierIntelligencePage,
} from "@/types/intelligence";
import type { RunListItem } from "@/types/runs";

type Section = "procurement" | "suppliers" | "inventory";
type InsightData =
  | { section: "procurement"; value: ProcurementIntelligence }
  | { section: "suppliers"; value: SupplierIntelligencePage }
  | { section: "inventory"; value: InventoryIntelligence }
  | null;

const unavailable = "Not available for this analysis mode.";
const title = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
    .join(" ");

export function InsightsPage() {
  const auth = useAuth();
  const role = auth.session?.memberships.find(
    (membership) =>
      membership.organization_id === auth.session?.active_organization_id,
  )?.role;
  if (!canViewInsights(role)) {
    return (
      <section className="space-y-3" aria-labelledby="insights-denied-title">
        <h1 id="insights-denied-title" className="text-2xl font-semibold">
          Insights access required
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Insights is available to AP managers and organization administrators.
          The server checks every request against the active membership.
        </p>
      </section>
    );
  }
  return <InsightsWorkspace />;
}

function InsightsWorkspace() {
  const [section, setSection] = useState<Section>("procurement");
  const [window, setWindow] = useState<IntelligenceWindow>("30d");
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [runId, setRunId] = useState("");
  const [runError, setRunError] = useState<string | null>(null);
  const runSelectId = useId();
  const windowSelectId = useId();

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      listRuns({ archived: false, limit: RUN_SELECTOR_LIMIT }, controller.signal),
      listRuns({ archived: true, limit: RUN_SELECTOR_LIMIT }, controller.signal),
    ]).then(
      ([active, archived]) => {
        const available = [...active.items, ...archived.items];
        setRuns(available);
        setRunId((current) =>
          available.some((run) => run.id === current)
            ? current
            : (available[0]?.id ?? ""),
        );
      },
      (error: unknown) => {
        if (!controller.signal.aborted)
          setRunError(
            error instanceof Error ? error.message : "Saved runs could not be loaded.",
          );
      },
    );
    return () => controller.abort();
  }, []);

  const load = useCallback(
    async (signal: AbortSignal): Promise<InsightData> => {
      if (section === "inventory")
        return {
          section,
          value: await getInventoryIntelligence(window, signal),
        };
      if (!runId) return null;
      if (section === "procurement")
        return {
          section,
          value: await getProcurementIntelligence(runId, signal),
        };
      return {
        section,
        value: await getSupplierIntelligence(runId, signal),
      };
    },
    [runId, section, window],
  );
  const resource = useRunResource(`${section}:${runId}:${window}`, load);
  const selected = runs.find((run) => run.id === runId);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <p className="text-sm font-semibold text-primary">Evidence-based read model</p>
        <h1 className="text-2xl font-semibold">Insights</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Procurement and supplier metrics describe one selected saved analysis.
          Inventory is current organization state from explicit stock-ledger entries.
        </p>
      </header>
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Insight sections">
        {(["procurement", "suppliers", "inventory"] as const).map((entry) => (
          <Button
            key={entry}
            role="tab"
            aria-selected={section === entry}
            variant={section === entry ? "default" : "outline"}
            onClick={() => setSection(entry)}
          >
            {title(entry)}
          </Button>
        ))}
      </div>
      {section !== "inventory" ? (
        <section className="space-y-3 rounded-md border bg-card p-4" aria-label="Run context">
          <p className="text-sm font-medium">
            Metrics below describe only the selected saved analysis.
          </p>
          <label htmlFor={runSelectId} className="block text-sm font-medium">
            Saved analysis
          </label>
          <select
            id={runSelectId}
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            className="w-full max-w-2xl rounded-md border bg-background p-2 text-sm"
          >
            {!runs.length && <option value="">No saved analyses available</option>}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.title ?? run.mode} · {new Date(run.completed_at).toLocaleDateString()}
                {run.archived_at ? " · archived" : ""}
              </option>
            ))}
          </select>
          {selected && (
            <p className="text-xs text-muted-foreground">
              {selected.mode} · completed <RunDate value={selected.completed_at} />
              {selected.archived_at ? " · archived" : ""}
            </p>
          )}
        </section>
      ) : (
        <section className="space-y-3 rounded-md border bg-card p-4" aria-label="Inventory context">
          <p className="text-sm font-medium">
            Imported goods receipts do not post inventory.
          </p>
          <p className="text-sm text-muted-foreground">
            Current on-hand uses all committed stock movements. Period activity uses
            operation occurred time with an included start and excluded end.
          </p>
          <label htmlFor={windowSelectId} className="block text-sm font-medium">
            Activity window
          </label>
          <select
            id={windowSelectId}
            value={window}
            onChange={(event) => setWindow(event.target.value as IntelligenceWindow)}
            className="rounded-md border bg-background p-2 text-sm"
          >
            {Object.entries(INTELLIGENCE_WINDOWS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </section>
      )}
      {runError && <p role="alert">{runError}</p>}
      {resource.loading && <p role="status">Loading insights…</p>}
      {resource.error && (
        <div className="space-y-3" role="alert">
          <p>{resource.error.message}</p>
          <Button variant="outline" onClick={resource.reload}>
            Retry insights
          </Button>
        </div>
      )}
      {!resource.loading && !resource.error && !resource.value && section !== "inventory" && (
        <p>No saved analysis is available. Complete an analysis to inspect its evidence.</p>
      )}
      {resource.value?.section === "procurement" && (
        <ProcurementSection value={resource.value.value} />
      )}
      {resource.value?.section === "suppliers" && (
        <SupplierSection value={resource.value.value} />
      )}
      {resource.value?.section === "inventory" && (
        <InventorySection value={resource.value.value} />
      )}
    </div>
  );
}

function ProcurementSection({ value }: { value: ProcurementIntelligence }) {
  return (
    <div className="space-y-8">
      <section className="space-y-4" aria-labelledby="procurement-summary">
        <h2 id="procurement-summary" className="text-xl font-semibold">
          Selected-run summary
        </h2>
        <Table aria-label="Selected run document and line counts">
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Evidence</TableHead>
              <TableHead scope="col">Documents</TableHead>
              <TableHead scope="col">Lines</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(["purchase_orders", "goods_receipts", "invoices"] as const).map((key) => (
              <TableRow key={key}>
                <TableHead scope="row">{title(key)}</TableHead>
                <TableCell>{value.documents[key] ?? unavailable}</TableCell>
                <TableCell>{value.lines[key] ?? unavailable}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="text-sm">
          Matched lines: {value.result_state.matched_lines ?? unavailable} · Review required:
          {" "}
          {value.result_state.review_required_lines ?? unavailable}
        </p>
      </section>
      <MoneyTable money={value.money} />
      <CountTable titleText="Issue mix" label="Issue code" values={value.issues.by_code} />
      {value.fulfillment ? (
        <CountTable titleText="PO-line fulfillment" label="State" values={value.fulfillment} />
      ) : (
        <section aria-labelledby="fulfillment-title" className="space-y-2">
          <h2 id="fulfillment-title" className="text-xl font-semibold">
            PO-line fulfillment
          </h2>
          <p>{unavailable}</p>
        </section>
      )}
    </div>
  );
}

function MoneyTable({ money }: { money: ProcurementIntelligence["money"] }) {
  const currencies = Array.from(
    new Set(
      Object.values(money)
        .filter((entry): entry is MoneyMap => entry !== null)
        .flatMap((entry) => Object.keys(entry)),
    ),
  ).sort();
  return (
    <section className="space-y-4" aria-labelledby="money-title">
      <h2 id="money-title" className="text-xl font-semibold">
        Exact value by currency
      </h2>
      {!currencies.length ? (
        <p>{unavailable}</p>
      ) : (
        <Table aria-label="Selected run values separated by currency">
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Currency</TableHead>
              <TableHead scope="col">Ordered value</TableHead>
              <TableHead scope="col">Invoiced value</TableHead>
              <TableHead scope="col">Authoritative disputed amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {currencies.map((currency) => (
              <TableRow key={currency}>
                <TableHead scope="row">{currency}</TableHead>
                <TableCell>
                  {money.ordered_value_by_currency
                    ? formatDecimalString(money.ordered_value_by_currency[currency] ?? "0")
                    : unavailable}
                </TableCell>
                <TableCell>
                  {money.invoiced_value_by_currency
                    ? formatDecimalString(money.invoiced_value_by_currency[currency] ?? "0")
                    : unavailable}
                </TableCell>
                <TableCell>
                  {money.authoritative_disputed_amounts_by_currency
                    ? formatDecimalString(
                        money.authoritative_disputed_amounts_by_currency[currency] ?? "0",
                      )
                    : unavailable}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <p className="text-xs text-muted-foreground">
        Values are source-document values, not payments, cash outflow, or savings.
      </p>
    </section>
  );
}

function CountTable({
  titleText,
  label,
  values,
}: {
  titleText: string;
  label: string;
  values: CountMap;
}) {
  return (
    <section className="space-y-4" aria-labelledby={`${label.replaceAll(" ", "-")}-title`}>
      <h2 id={`${label.replaceAll(" ", "-")}-title`} className="text-xl font-semibold">
        {titleText}
      </h2>
      {!Object.keys(values).length ? (
        <p>No recorded entries.</p>
      ) : (
        <Table aria-label={titleText}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{label}</TableHead>
              <TableHead scope="col">Count</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(values).map(([key, count]) => (
              <TableRow key={key}>
                <TableHead scope="row">{title(key)}</TableHead>
                <TableCell>{count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function SupplierSection({ value }: { value: SupplierIntelligencePage }) {
  if (!value.items.length) return <p>No supplier evidence is available in this analysis.</p>;
  return (
    <section className="space-y-4" aria-labelledby="supplier-title">
      <h2 id="supplier-title" className="text-xl font-semibold">
        Suppliers observed in this analysis
      </h2>
      <p className="text-sm text-muted-foreground">
        Descriptive evidence only. There is no supplier score, ranking, or on-time-delivery
        claim.
      </p>
      <Table aria-label="Selected run supplier evidence">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Supplier</TableHead>
            <TableHead scope="col">PO documents / lines</TableHead>
            <TableHead scope="col">Ordered value</TableHead>
            <TableHead scope="col">Invoice documents / lines</TableHead>
            <TableHead scope="col">Invoiced value</TableHead>
            <TableHead scope="col">Review lines</TableHead>
            <TableHead scope="col">Issues</TableHead>
            <TableHead scope="col">Receiving</TableHead>
            <TableHead scope="col">Observed receipt days</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {value.items.map((supplier) => (
            <SupplierRow key={supplier.identity.supplier_code} value={supplier} />
          ))}
        </TableBody>
      </Table>
      {value.next_cursor && (
        <p className="text-sm text-muted-foreground">
          More suppliers are available in the next bounded page.
        </p>
      )}
    </section>
  );
}

function MoneyValues({ values }: { values: MoneyMap | null }) {
  if (values === null) return <>{unavailable}</>;
  if (!Object.keys(values).length) return <>None in this analysis.</>;
  return (
    <ul className="space-y-1">
      {Object.entries(values).map(([currency, amount]) => (
        <li key={currency}>
          {currency} {formatDecimalString(amount)}
        </li>
      ))}
    </ul>
  );
}

function SupplierRow({ value }: { value: SupplierIntelligence }) {
  const timing = value.receipt_timing;
  return (
    <TableRow>
      <TableHead scope="row" className="whitespace-normal">
        {value.identity.supplier_name ?? `Unresolved supplier: ${value.identity.supplier_code}`}
        {value.identity.supplier_name && (
          <span className="block text-xs font-normal text-muted-foreground">
            {value.identity.supplier_code}
          </span>
        )}
      </TableHead>
      <TableCell>
        {value.purchase_orders.document_count === null
          ? unavailable
          : `${value.purchase_orders.document_count} / ${value.purchase_orders.line_count}`}
      </TableCell>
      <TableCell>
        <MoneyValues values={value.purchase_orders.ordered_value_by_currency} />
      </TableCell>
      <TableCell>
        {value.invoices.document_count === null
          ? unavailable
          : `${value.invoices.document_count} / ${value.invoices.line_count}`}
      </TableCell>
      <TableCell>
        <MoneyValues values={value.invoices.invoiced_value_by_currency} />
      </TableCell>
      <TableCell>{value.invoices.review_line_count ?? unavailable}</TableCell>
      <TableCell>
        {Object.entries(value.issues.by_code)
          .map(([code, count]) => `${code}: ${count}`)
          .join(" · ") || "None"}
      </TableCell>
      <TableCell>
        {value.receiving
          ? Object.entries(value.receiving)
              .map(([state, count]) => `${title(state)}: ${count}`)
              .join(" · ")
          : unavailable}
      </TableCell>
      <TableCell className="whitespace-normal">
        {timing
          ? `First: ${timing.median_observed_days_to_first_receipt ?? "—"} across ${timing.first_receipt_eligible_line_count}; full: ${timing.median_observed_days_to_full_receipt ?? "—"} across ${timing.full_receipt_eligible_line_count}`
          : unavailable}
      </TableCell>
    </TableRow>
  );
}

function InventorySection({ value }: { value: InventoryIntelligence }) {
  return (
    <div className="space-y-8">
      <section className="space-y-4" aria-labelledby="inventory-overview">
        <h2 id="inventory-overview" className="text-xl font-semibold">
          Current ledger overview
        </h2>
        <dl className="grid gap-4 sm:grid-cols-3">
          <Metric name="Active items" value={value.summary.active_inventory_item_count} />
          <Metric name="Active locations" value={value.summary.active_inventory_location_count} />
          <Metric
            name="Positive item/location positions"
            value={value.summary.positive_item_location_position_count}
          />
        </dl>
        <p className="text-xs text-muted-foreground">
          Activity period: {value.period.start} to {value.period.end} UTC. Checked{" "}
          <RunDate value={value.server_now} />.
        </p>
      </section>
      <CountTable
        titleText="Operations in selected period"
        label="Operation type"
        values={value.summary.operation_counts_by_type}
      />
      <section className="space-y-4" aria-labelledby="inventory-activity">
        <h2 id="inventory-activity" className="text-xl font-semibold">
          Item/location activity
        </h2>
        {!value.items.length ? (
          <p>No stock-ledger positions have been recorded.</p>
        ) : (
          <Table aria-label="Current item and location ledger activity">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Item</TableHead>
                <TableHead scope="col">Location</TableHead>
                <TableHead scope="col">Current on-hand</TableHead>
                <TableHead scope="col">Period operations</TableHead>
                <TableHead scope="col">Period ledger net delta</TableHead>
                <TableHead scope="col">Last movement</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {value.items.map((row) => (
                <TableRow key={`${row.item.id}:${row.location.id}`}>
                  <TableHead scope="row" className="whitespace-normal">
                    {row.item.item_code}
                    <span className="block text-xs font-normal text-muted-foreground">
                      {row.item.description}
                    </span>
                  </TableHead>
                  <TableCell>{row.location.location_code}</TableCell>
                  <TableCell>
                    {formatDecimalString(row.current_on_hand)} {row.item.base_uom ?? "unit unset"}
                  </TableCell>
                  <TableCell>{row.operation_count}</TableCell>
                  <TableCell>
                    {formatDecimalString(row.net_ledger_quantity_delta)}{" "}
                    {row.item.base_uom ?? "unit unset"}
                  </TableCell>
                  <TableCell>
                    {row.last_movement_at ? <RunDate value={row.last_movement_at} /> : "Never"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {value.next_cursor && (
          <p className="text-sm text-muted-foreground">
            More item/location positions are available in the next bounded page.
          </p>
        )}
      </section>
    </div>
  );
}

function Metric({ name, value }: { name: string; value: number }) {
  return (
    <div className="rounded-md border bg-card p-4">
      <dt className="text-sm text-muted-foreground">{name}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
