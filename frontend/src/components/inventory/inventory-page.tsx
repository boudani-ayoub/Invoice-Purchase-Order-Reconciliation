"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  canManageInventory,
  canViewInventory,
  INVENTORY_BASE_UOM_LIMIT,
  INVENTORY_CODE_LIMIT,
  INVENTORY_NAME_LIMIT,
  INVENTORY_NOTE_LIMIT,
  INVENTORY_OPERATION_TYPES,
  INVENTORY_REFERENCE_LIMIT,
} from "@/constants/inventory";
import {
  createInventoryItem,
  createInventoryLocation,
  getInventoryBalances,
  getInventoryItems,
  getInventoryLocations,
  getInventoryOperations,
  InventoryRequestError,
  postInventoryMovement,
  postInventoryTransfer,
  reverseInventoryOperation,
  setInventoryItemArchived,
  setInventoryLocationArchived,
  updateInventoryItem,
  updateInventoryLocation,
} from "@/lib/api/inventory";
import { formatDecimalString } from "@/lib/formatters";
import type {
  InventoryBalance,
  InventoryItem,
  InventoryLocation,
  InventoryOperation,
  InventoryOperationType,
  MovementIntent,
  TransferIntent,
} from "@/types/inventory";

type PostingIntent = MovementIntent | TransferIntent;

const label = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
    .join(" ");

const timestamp = (value: string) => new Date(value).toLocaleString();

export function InventoryPage() {
  const { session } = useAuth();
  const active = session?.memberships.find(
    (membership) => membership.organization_id === session.active_organization_id,
  );
  const canView = canViewInventory(active?.role);
  const canManage = canManageInventory(active?.role);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [locations, setLocations] = useState<InventoryLocation[]>([]);
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [operations, setOperations] = useState<InventoryOperation[]>([]);
  const [kind, setKind] = useState<InventoryOperationType>("STOCK_RECEIPT");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [ambiguousPosting, setAmbiguousPosting] = useState(false);
  const [pendingPosting, setPendingPosting] = useState<PostingIntent | null>(null);
  const [pendingReversal, setPendingReversal] = useState<{
    operationId: string;
    key: string;
  } | null>(null);
  const feedback = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    if (!canView) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setConflict(false);
    try {
      const [itemPage, locationPage, balancePage, operationPage] = await Promise.all([
        getInventoryItems(),
        getInventoryLocations(),
        getInventoryBalances(),
        getInventoryOperations(),
      ]);
      setItems(itemPage.items);
      setLocations(locationPage.items);
      setBalances(balancePage.items);
      setOperations(operationPage.items);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Inventory could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [canView]);

  useEffect(() => {
    const pending = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(pending);
  }, [refresh]);

  useEffect(() => {
    if (error || message) feedback.current?.focus();
  }, [error, message]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    if (busy) return false;
    setBusy(true);
    setError(null);
    setMessage(null);
    setConflict(false);
    try {
      await action();
      setMessage(success);
      await refresh();
      return true;
    } catch (caught) {
      setConflict(caught instanceof InventoryRequestError && caught.status === 409);
      setError(caught instanceof Error ? caught.message : "The action could not be completed.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const succeeded = await mutate(
      () =>
        createInventoryItem(
          String(data.get("item_code") ?? ""),
          String(data.get("description") ?? ""),
          String(data.get("base_uom") ?? ""),
        ),
      "Item created.",
    );
    if (succeeded) form.reset();
  }

  async function createLocation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const succeeded = await mutate(
      () =>
        createInventoryLocation(
          String(data.get("location_code") ?? ""),
          String(data.get("name") ?? ""),
        ),
      "Location created.",
    );
    if (succeeded) form.reset();
  }

  function buildPosting(form: HTMLFormElement): PostingIntent {
    const data = new FormData(form);
    const common = {
      idempotency_key: crypto.randomUUID(),
      item_id: String(data.get("item_id") ?? ""),
      quantity: String(data.get("quantity") ?? ""),
      external_reference: String(data.get("external_reference") ?? "") || undefined,
      note: String(data.get("note") ?? "") || undefined,
    };
    return kind === "TRANSFER"
      ? {
          ...common,
          source_location_id: String(data.get("location_id") ?? ""),
          destination_location_id: String(data.get("destination_location_id") ?? ""),
        }
      : {
          ...common,
          type: kind,
          location_id: String(data.get("location_id") ?? ""),
        };
  }

  async function sendPosting(intent: PostingIntent) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    setConflict(false);
    try {
      if ("type" in intent) await postInventoryMovement(intent);
      else await postInventoryTransfer(intent);
      setPendingPosting(null);
      setAmbiguousPosting(false);
      setMessage("Inventory operation posted.");
      await refresh();
    } catch (caught) {
      const ambiguous = caught instanceof InventoryRequestError && caught.status === 0;
      setAmbiguousPosting(ambiguous);
      if (!ambiguous) setPendingPosting(null);
      setConflict(caught instanceof InventoryRequestError && caught.status === 409);
      setError(caught instanceof Error ? caught.message : "The operation could not be posted.");
    } finally {
      setBusy(false);
    }
  }

  async function submitPosting(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intent = pendingPosting ?? buildPosting(event.currentTarget);
    setPendingPosting(intent);
    await sendPosting(intent);
  }

  async function reverse(operationId: string, key = crypto.randomUUID()) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    setConflict(false);
    try {
      await reverseInventoryOperation(operationId, key, "Correction posted from inventory history");
      setPendingReversal(null);
      setMessage("Reversal posted.");
      await refresh();
    } catch (caught) {
      setConflict(caught instanceof InventoryRequestError && caught.status === 409);
      if (caught instanceof InventoryRequestError && caught.status === 0) {
        setPendingReversal({ operationId, key });
      } else {
        setPendingReversal(null);
      }
      setError(caught instanceof Error ? caught.message : "The reversal could not be posted.");
    } finally {
      setBusy(false);
    }
  }

  if (!canView) {
    return (
      <section className="space-y-3" aria-labelledby="inventory-denied-title">
        <h1 id="inventory-denied-title" className="text-2xl font-semibold">
          Inventory access required
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Inventory is currently available to AP managers and organization administrators.
          The server checks every request against the active membership.
        </p>
      </section>
    );
  }

  const activeItems = items.filter(
    (item) => item.status === "ACTIVE" && item.base_uom !== null,
  );
  const activeLocations = locations.filter((location) => location.status === "ACTIVE");

  return (
    <div className="space-y-10">
      <section className="space-y-4" aria-labelledby="inventory-title">
        <div>
          <p className="text-sm font-semibold text-primary">Operational ledger</p>
          <h1 id="inventory-title" className="mt-1 text-2xl font-semibold">
            Current on-hand inventory
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Balances come only from explicit stock operations. Imported goods receipts and
            reconciliation runs never post inventory automatically.
          </p>
        </div>
        {(error || message) && (
          <div
            ref={feedback}
            tabIndex={-1}
            role={error ? "alert" : "status"}
            className={`flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm ${
              error ? "border-destructive/40 text-destructive" : "text-foreground"
            }`}
          >
            <span>{error ?? message}</span>
            <div className="flex flex-wrap gap-2">
              {conflict && (
                <Button type="button" variant="outline" onClick={() => void refresh()}>
                  Refresh
                </Button>
              )}
              {ambiguousPosting && pendingPosting && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void sendPosting(pendingPosting)}
                  >
                    Retry same posting
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      setPendingPosting(null);
                      setAmbiguousPosting(false);
                    }}
                  >
                    Discard retry
                  </Button>
                </>
              )}
              {pendingReversal && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void reverse(pendingReversal.operationId, pendingReversal.key)
                  }
                >
                  Retry same reversal
                </Button>
              )}
            </div>
          </div>
        )}
        {loading ? (
          <p role="status">Loading inventory…</p>
        ) : balances.length ? (
          <Table scrollLabel="Current on-hand inventory">
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Location</TableHead>
                <TableHead className="text-right">On-hand</TableHead>
                <TableHead>Base unit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {balances.map((balance) => (
                <TableRow key={`${balance.item.id}:${balance.location.id}`}>
                  <TableCell className="font-medium">{balance.item.item_code}</TableCell>
                  <TableCell>{balance.item.description}</TableCell>
                  <TableCell>{balance.location.location_code}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatDecimalString(balance.quantity)}
                  </TableCell>
                  <TableCell>{balance.item.base_uom}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
            No stock has been posted. Configure an item and location, then post an opening
            balance.
          </p>
        )}
      </section>

      {canManage && (
        <section className="space-y-5" aria-labelledby="posting-title">
          <div>
            <h2 id="posting-title" className="text-xl font-semibold">
              Post inventory
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Enter positive quantities. The server owns every movement sign and rejects
              negative on-hand results.
            </p>
          </div>
          <form
            aria-label="Post inventory operation"
            onSubmit={submitPosting}
            className="grid gap-4 rounded-lg border bg-card p-4 sm:grid-cols-2 lg:grid-cols-3"
          >
            <div className="space-y-2">
              <Label htmlFor="operation-type">Operation</Label>
              <select
                id="operation-type"
                className="block h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={kind}
                disabled={busy || ambiguousPosting}
                onChange={(event) => setKind(event.target.value as InventoryOperationType)}
              >
                {[...INVENTORY_OPERATION_TYPES, "TRANSFER" as const].map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="posting-item">Item</Label>
              <select
                id="posting-item"
                name="item_id"
                className="block h-9 w-full rounded-md border bg-background px-3 text-sm"
                required
                disabled={busy || ambiguousPosting}
              >
                <option value="">Choose an item</option>
                {activeItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.item_code} · {item.base_uom}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="posting-location">
                {kind === "TRANSFER" ? "Source location" : "Location"}
              </Label>
              <select
                id="posting-location"
                name="location_id"
                className="block h-9 w-full rounded-md border bg-background px-3 text-sm"
                required
                disabled={busy || ambiguousPosting}
              >
                <option value="">Choose a location</option>
                {activeLocations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.location_code}
                  </option>
                ))}
              </select>
            </div>
            {kind === "TRANSFER" && (
              <div className="space-y-2">
                <Label htmlFor="posting-destination">Destination location</Label>
                <select
                  id="posting-destination"
                  name="destination_location_id"
                  className="block h-9 w-full rounded-md border bg-background px-3 text-sm"
                  required
                  disabled={busy || ambiguousPosting}
                >
                  <option value="">Choose a location</option>
                  {activeLocations.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.location_code}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="posting-quantity">Quantity</Label>
              <Input
                id="posting-quantity"
                name="quantity"
                inputMode="decimal"
                pattern="[0-9]+([.][0-9]+)?"
                placeholder="12.500"
                required
                disabled={busy || ambiguousPosting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="posting-reference">External reference (optional)</Label>
              <Input
                id="posting-reference"
                name="external_reference"
                maxLength={INVENTORY_REFERENCE_LIMIT}
                disabled={busy || ambiguousPosting}
              />
            </div>
            <div className="space-y-2 sm:col-span-2 lg:col-span-3">
              <Label htmlFor="posting-note">Note (optional)</Label>
              <Input
                id="posting-note"
                name="note"
                maxLength={INVENTORY_NOTE_LIMIT}
                disabled={busy || ambiguousPosting}
              />
            </div>
            <div>
              <Button type="submit" disabled={busy || ambiguousPosting}>
                {busy ? "Posting…" : "Post operation"}
              </Button>
            </div>
          </form>
        </section>
      )}

      <section className="space-y-5" aria-labelledby="history-title">
        <div>
          <h2 id="history-title" className="text-xl font-semibold">
            Movement history
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Posted operations are retained. Corrections create exact reversal entries.
          </p>
        </div>
        {operations.length ? (
          <Table scrollLabel="Inventory movement history">
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Movement</TableHead>
                <TableHead>Occurred</TableHead>
                <TableHead>Recorded</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Reference</TableHead>
                {canManage && <TableHead>Action</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {operations.map((operation) => (
                <TableRow key={operation.id}>
                  <TableCell className="font-medium">{label(operation.type)}</TableCell>
                  <TableCell>
                    <ul className="space-y-1">
                      {operation.movements.map((movement) => (
                        <li key={movement.id}>
                          {movement.item.item_code} · {movement.location.location_code} ·{" "}
                          <span className="font-mono">
                            {formatDecimalString(movement.quantity_delta)}{" "}
                            {movement.item.base_uom}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </TableCell>
                  <TableCell>{timestamp(operation.occurred_at)}</TableCell>
                  <TableCell>{timestamp(operation.created_at)}</TableCell>
                  <TableCell className="font-mono text-xs">{operation.actor_user_id}</TableCell>
                  <TableCell>{operation.external_reference ?? "—"}</TableCell>
                  {canManage && (
                    <TableCell>
                      {operation.type !== "REVERSAL" && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy || pendingReversal !== null}
                          onClick={() => void reverse(operation.id)}
                        >
                          Reverse
                        </Button>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">No inventory operations recorded.</p>
        )}
      </section>

      <section className="space-y-5" aria-labelledby="master-title">
        <div>
          <h2 id="master-title" className="text-xl font-semibold">
            Inventory master data
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Item and location codes are permanent. Base units become permanent after the first
            movement.
          </p>
        </div>
        {canManage && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Create item</CardTitle>
                <CardDescription>Use one base unit; unit conversion is not provided.</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={createItem} className="grid gap-3 sm:grid-cols-3">
                  <Label className="space-y-2">
                    <span>Item code</span>
                    <Input
                      name="item_code"
                      maxLength={INVENTORY_CODE_LIMIT}
                      required
                      disabled={busy}
                    />
                  </Label>
                  <Label className="space-y-2">
                    <span>Description</span>
                    <Input
                      name="description"
                      maxLength={INVENTORY_NAME_LIMIT}
                      required
                      disabled={busy}
                    />
                  </Label>
                  <Label className="space-y-2">
                    <span>Base unit</span>
                    <Input
                      name="base_uom"
                      maxLength={INVENTORY_BASE_UOM_LIMIT}
                      required
                      disabled={busy}
                    />
                  </Label>
                  <Button type="submit" disabled={busy} className="sm:col-span-3 sm:w-fit">
                    Create item
                  </Button>
                </form>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Create location</CardTitle>
                <CardDescription>Phase 7 uses a flat location list.</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={createLocation} className="grid gap-3 sm:grid-cols-2">
                  <Label className="space-y-2">
                    <span>Location code</span>
                    <Input
                      name="location_code"
                      maxLength={INVENTORY_CODE_LIMIT}
                      required
                      disabled={busy}
                    />
                  </Label>
                  <Label className="space-y-2">
                    <span>Location name</span>
                    <Input
                      name="name"
                      maxLength={INVENTORY_NAME_LIMIT}
                      required
                      disabled={busy}
                    />
                  </Label>
                  <Button type="submit" disabled={busy} className="sm:col-span-2 sm:w-fit">
                    Create location
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        )}

        <div className="grid gap-6 xl:grid-cols-2">
          <MasterItems
            items={items}
            canManage={canManage}
            busy={busy}
            mutate={mutate}
          />
          <MasterLocations
            locations={locations}
            canManage={canManage}
            busy={busy}
            mutate={mutate}
          />
        </div>
      </section>
    </div>
  );
}

function MasterItems({
  items,
  canManage,
  busy,
  mutate,
}: {
  items: InventoryItem[];
  canManage: boolean;
  busy: boolean;
  mutate: (action: () => Promise<unknown>, success: string) => Promise<boolean>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Items</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((item) => (
          <form
            key={`${item.id}:${item.version}`}
            aria-label={`Edit item ${item.item_code}`}
            className="grid gap-3 border-b pb-4 last:border-0"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void mutate(
                () =>
                  updateInventoryItem(item, {
                    description: String(data.get("description") ?? ""),
                    base_uom: String(data.get("base_uom") ?? "") || null,
                  }),
                "Item updated.",
              );
            }}
          >
            <p className="font-medium">{item.item_code}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Label className="space-y-2">
                <span>Description</span>
                <Input
                  name="description"
                  defaultValue={item.description}
                  maxLength={INVENTORY_NAME_LIMIT}
                  required
                  disabled={!canManage || busy}
                />
              </Label>
              <Label className="space-y-2">
                <span>Base unit</span>
                <Input
                  name="base_uom"
                  defaultValue={item.base_uom ?? ""}
                  maxLength={INVENTORY_BASE_UOM_LIMIT}
                  disabled={!canManage || busy}
                />
              </Label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{label(item.status)}</span>
              {canManage && (
                <>
                  <Button type="submit" size="sm" disabled={busy}>
                    Save item
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void mutate(
                        () =>
                          setInventoryItemArchived(item, item.status === "ACTIVE"),
                        item.status === "ACTIVE" ? "Item archived." : "Item restored.",
                      )
                    }
                  >
                    {item.status === "ACTIVE" ? "Archive" : "Restore"}
                  </Button>
                </>
              )}
            </div>
          </form>
        ))}
      </CardContent>
    </Card>
  );
}

function MasterLocations({
  locations,
  canManage,
  busy,
  mutate,
}: {
  locations: InventoryLocation[];
  canManage: boolean;
  busy: boolean;
  mutate: (action: () => Promise<unknown>, success: string) => Promise<boolean>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Locations</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {locations.map((location) => (
          <form
            key={`${location.id}:${location.version}`}
            aria-label={`Edit location ${location.location_code}`}
            className="grid gap-3 border-b pb-4 last:border-0"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void mutate(
                () =>
                  updateInventoryLocation(location, String(data.get("name") ?? "")),
                "Location updated.",
              );
            }}
          >
            <p className="font-medium">{location.location_code}</p>
            <Label className="space-y-2">
              <span>Name</span>
              <Input
                name="name"
                defaultValue={location.name}
                maxLength={INVENTORY_NAME_LIMIT}
                required
                disabled={!canManage || busy}
              />
            </Label>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{label(location.status)}</span>
              {canManage && (
                <>
                  <Button type="submit" size="sm" disabled={busy}>
                    Save location
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void mutate(
                        () =>
                          setInventoryLocationArchived(
                            location,
                            location.status === "ACTIVE",
                          ),
                        location.status === "ACTIVE"
                          ? "Location archived."
                          : "Location restored.",
                      )
                    }
                  >
                    {location.status === "ACTIVE" ? "Archive" : "Restore"}
                  </Button>
                </>
              )}
            </div>
          </form>
        ))}
      </CardContent>
    </Card>
  );
}
