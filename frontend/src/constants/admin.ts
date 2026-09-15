import type { MembershipRole } from "@/types/auth";

export const ADMIN_PATH = "/admin";
export const ADMIN_API_PATH = "/api/v1/admin";
export const ADMIN_PAGE_SIZE = 25;
export const MEMBERSHIP_ROLES: readonly MembershipRole[] = [
  "MEMBER",
  "AP_MANAGER",
  "ORG_ADMIN",
];

export function canViewAdmin(role?: MembershipRole): boolean {
  return role === "ORG_ADMIN";
}
