import type { MembershipRole } from "@/types/auth";
import type { InventoryOperationType } from "@/types/inventory";

export const INVENTORY_PATH = "/inventory";
export const INVENTORY_API_PATH = "/api/v1/inventory";
export const INVENTORY_PAGE_SIZE = 25;
export const INVENTORY_CODE_LIMIT = 64;
export const INVENTORY_NAME_LIMIT = 200;
export const INVENTORY_REFERENCE_LIMIT = 200;
export const INVENTORY_NOTE_LIMIT = 1_000;
export const INVENTORY_BASE_UOM_LIMIT = 16;
export const INVENTORY_OPERATION_TYPES: readonly InventoryOperationType[] = [
  "OPENING_BALANCE",
  "STOCK_RECEIPT",
  "STOCK_ISSUE",
  "ADJUSTMENT_IN",
  "ADJUSTMENT_OUT",
];

export function canViewInventory(role?: MembershipRole): boolean {
  return role === "AP_MANAGER" || role === "ORG_ADMIN";
}

export function canManageInventory(role?: MembershipRole): boolean {
  return role === "ORG_ADMIN";
}
