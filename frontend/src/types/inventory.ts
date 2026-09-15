export type InventoryStatus = "ACTIVE" | "ARCHIVED";
export type InventoryOperationType =
  | "OPENING_BALANCE"
  | "STOCK_RECEIPT"
  | "STOCK_ISSUE"
  | "ADJUSTMENT_IN"
  | "ADJUSTMENT_OUT"
  | "TRANSFER"
  | "REVERSAL";

export interface InventoryItem {
  id: string;
  item_code: string;
  description: string;
  base_uom: string | null;
  status: InventoryStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface InventoryLocation {
  id: string;
  location_code: string;
  name: string;
  status: InventoryStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface InventoryBalance {
  item: InventoryItem;
  location: InventoryLocation;
  quantity: string;
}

export interface StockMovement {
  id: string;
  item: Pick<InventoryItem, "id" | "item_code" | "description" | "base_uom">;
  location: Pick<InventoryLocation, "id" | "location_code" | "name">;
  quantity_delta: string;
}

export interface InventoryOperation {
  id: string;
  type: InventoryOperationType;
  actor_user_id: string;
  occurred_at: string;
  created_at: string;
  external_reference: string | null;
  note: string | null;
  request_id: string;
  idempotency_key: string;
  reverses_operation_id: string | null;
  movements: StockMovement[];
}

export interface InventoryPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface MovementIntent {
  idempotency_key: string;
  type: InventoryOperationType;
  item_id: string;
  location_id: string;
  quantity: string;
  occurred_at?: string;
  external_reference?: string;
  note?: string;
}

export interface TransferIntent {
  idempotency_key: string;
  item_id: string;
  source_location_id: string;
  destination_location_id: string;
  quantity: string;
  occurred_at?: string;
  external_reference?: string;
  note?: string;
}
