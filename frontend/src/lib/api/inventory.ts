import {
  INVENTORY_API_PATH,
  INVENTORY_BASE_UOM_LIMIT,
  INVENTORY_CODE_LIMIT,
  INVENTORY_NAME_LIMIT,
  INVENTORY_NOTE_LIMIT,
  INVENTORY_OPERATION_TYPES,
  INVENTORY_PAGE_SIZE,
  INVENTORY_REFERENCE_LIMIT,
} from "@/constants/inventory";
import { apiFetch } from "@/lib/api/transport";
import type {
  InventoryBalance,
  InventoryItem,
  InventoryLocation,
  InventoryOperation,
  InventoryOperationType,
  InventoryPage,
  MovementIntent,
  StockMovement,
  TransferIntent,
} from "@/types/inventory";

export class InventoryRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "InventoryRequestError";
  }
}

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const nullableText = (value: unknown) => value === null || text(value);
const boundedText = (value: unknown, limit: number) =>
  text(value) && value.length <= limit;
const decimalString = (value: unknown, signed = false) =>
  text(value) &&
  new RegExp(`^${signed ? "-?" : ""}(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$`).test(
    value,
  );
const timestamp = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const version = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const status = (value: unknown) => ["ACTIVE", "ARCHIVED"].includes(String(value));
const operationType = (value: unknown): value is InventoryOperationType =>
  [...INVENTORY_OPERATION_TYPES, "TRANSFER", "REVERSAL"].includes(
    value as InventoryOperationType,
  );

function invalid(): never {
  throw new InventoryRequestError(
    0,
    "The inventory response could not be read. Refresh to try again.",
  );
}

async function request(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(path, options);
  } catch {
    throw new InventoryRequestError(
      0,
      "Unable to reach inventory. Retry with the same posting key.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return invalid();
  }
  if (!response.ok) {
    const defaults: Record<number, string> = {
      401: "Your session expired. Sign in again.",
      403: "Your current role does not permit this inventory action.",
      404: "The requested inventory resource was not found.",
      409: "Inventory changed. Refresh before trying again.",
      422: "Check the supplied inventory fields.",
    };
    throw new InventoryRequestError(
      response.status,
      object(payload) && text(payload.message)
        ? payload.message
        : (defaults[response.status] ?? "The inventory request could not be completed."),
    );
  }
  return payload;
}

function json(method: "POST" | "PATCH", body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function item(value: unknown): value is InventoryItem {
  return (
    object(value) &&
    text(value.id) &&
    boundedText(value.item_code, INVENTORY_CODE_LIMIT) &&
    boundedText(value.description, INVENTORY_NAME_LIMIT) &&
    (value.base_uom === null ||
      boundedText(value.base_uom, INVENTORY_BASE_UOM_LIMIT)) &&
    status(value.status) &&
    version(value.version) &&
    timestamp(value.created_at) &&
    timestamp(value.updated_at)
  );
}

function location(value: unknown): value is InventoryLocation {
  return (
    object(value) &&
    text(value.id) &&
    boundedText(value.location_code, INVENTORY_CODE_LIMIT) &&
    boundedText(value.name, INVENTORY_NAME_LIMIT) &&
    status(value.status) &&
    version(value.version) &&
    timestamp(value.created_at) &&
    timestamp(value.updated_at)
  );
}

function movement(value: unknown): value is StockMovement {
  return (
    object(value) &&
    text(value.id) &&
    object(value.item) &&
    text(value.item.id) &&
    boundedText(value.item.item_code, INVENTORY_CODE_LIMIT) &&
    boundedText(value.item.description, INVENTORY_NAME_LIMIT) &&
    (value.item.base_uom === null ||
      boundedText(value.item.base_uom, INVENTORY_BASE_UOM_LIMIT)) &&
    object(value.location) &&
    text(value.location.id) &&
    boundedText(value.location.location_code, INVENTORY_CODE_LIMIT) &&
    boundedText(value.location.name, INVENTORY_NAME_LIMIT) &&
    decimalString(value.quantity_delta, true)
  );
}

function operation(value: unknown): value is InventoryOperation {
  return (
    object(value) &&
    text(value.id) &&
    operationType(value.type) &&
    text(value.actor_user_id) &&
    timestamp(value.occurred_at) &&
    timestamp(value.created_at) &&
    (value.external_reference === null ||
      boundedText(value.external_reference, INVENTORY_REFERENCE_LIMIT)) &&
    (value.note === null || boundedText(value.note, INVENTORY_NOTE_LIMIT)) &&
    text(value.request_id) &&
    text(value.idempotency_key) &&
    nullableText(value.reverses_operation_id) &&
    Array.isArray(value.movements) &&
    value.movements.length > 0 &&
    value.movements.every(movement)
  );
}

function balance(value: unknown): value is InventoryBalance {
  return (
    object(value) &&
    item(value.item) &&
    location(value.location) &&
    decimalString(value.quantity)
  );
}

function page<T>(value: unknown, guard: (entry: unknown) => entry is T): InventoryPage<T> {
  if (
    !object(value) ||
    !Array.isArray(value.items) ||
    value.items.length > INVENTORY_PAGE_SIZE ||
    !value.items.every(guard) ||
    !(value.next_cursor === null || text(value.next_cursor))
  )
    return invalid();
  return value as unknown as InventoryPage<T>;
}

function pagePath(resource: string): string {
  return `${INVENTORY_API_PATH}/${resource}?limit=${INVENTORY_PAGE_SIZE}`;
}

export async function getInventoryItems(): Promise<InventoryPage<InventoryItem>> {
  return page(await request(pagePath("items")), item);
}

export async function createInventoryItem(
  itemCode: string,
  description: string,
  baseUom: string,
): Promise<InventoryItem> {
  const value = await request(
    `${INVENTORY_API_PATH}/items`,
    json("POST", { item_code: itemCode, description, base_uom: baseUom }),
  );
  return item(value) ? value : invalid();
}

export async function updateInventoryItem(
  value: InventoryItem,
  changes: { description?: string; base_uom?: string | null },
): Promise<InventoryItem> {
  const result = await request(
    `${INVENTORY_API_PATH}/items/${encodeURIComponent(value.id)}`,
    json("PATCH", { expected_version: value.version, ...changes }),
  );
  return item(result) ? result : invalid();
}

export async function setInventoryItemArchived(
  value: InventoryItem,
  archived: boolean,
): Promise<InventoryItem> {
  const result = await request(
    `${INVENTORY_API_PATH}/items/${encodeURIComponent(value.id)}/${archived ? "archive" : "restore"}`,
    json("POST", { expected_version: value.version }),
  );
  return item(result) ? result : invalid();
}

export async function getInventoryLocations(): Promise<
  InventoryPage<InventoryLocation>
> {
  return page(await request(pagePath("locations")), location);
}

export async function createInventoryLocation(
  locationCode: string,
  name: string,
): Promise<InventoryLocation> {
  const value = await request(
    `${INVENTORY_API_PATH}/locations`,
    json("POST", { location_code: locationCode, name }),
  );
  return location(value) ? value : invalid();
}

export async function updateInventoryLocation(
  value: InventoryLocation,
  name: string,
): Promise<InventoryLocation> {
  const result = await request(
    `${INVENTORY_API_PATH}/locations/${encodeURIComponent(value.id)}`,
    json("PATCH", { expected_version: value.version, name }),
  );
  return location(result) ? result : invalid();
}

export async function setInventoryLocationArchived(
  value: InventoryLocation,
  archived: boolean,
): Promise<InventoryLocation> {
  const result = await request(
    `${INVENTORY_API_PATH}/locations/${encodeURIComponent(value.id)}/${archived ? "archive" : "restore"}`,
    json("POST", { expected_version: value.version }),
  );
  return location(result) ? result : invalid();
}

export async function getInventoryBalances(): Promise<InventoryPage<InventoryBalance>> {
  return page(await request(pagePath("balances")), balance);
}

export async function getInventoryOperations(): Promise<
  InventoryPage<InventoryOperation>
> {
  return page(await request(pagePath("operations")), operation);
}

export async function postInventoryMovement(
  intent: MovementIntent,
): Promise<InventoryOperation> {
  const value = await request(`${INVENTORY_API_PATH}/movements`, json("POST", intent));
  return operation(value) ? value : invalid();
}

export async function postInventoryTransfer(
  intent: TransferIntent,
): Promise<InventoryOperation> {
  const value = await request(`${INVENTORY_API_PATH}/transfers`, json("POST", intent));
  return operation(value) ? value : invalid();
}

export async function reverseInventoryOperation(
  operationId: string,
  idempotencyKey: string,
  note?: string,
): Promise<InventoryOperation> {
  const value = await request(
    `${INVENTORY_API_PATH}/operations/${encodeURIComponent(operationId)}/reverse`,
    json("POST", { idempotency_key: idempotencyKey, note }),
  );
  return operation(value) ? value : invalid();
}
