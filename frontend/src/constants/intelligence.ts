import type { MembershipRole } from "@/types/auth";
import type { IntelligenceWindow } from "@/types/intelligence";

export const INSIGHTS_PATH = "/insights";
export const INTELLIGENCE_API_PATH = "/api/v1/intelligence";
export const INTELLIGENCE_PAGE_SIZE = 25;
export const RUN_SELECTOR_LIMIT = 100;
export const INTELLIGENCE_WINDOWS: Record<IntelligenceWindow, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
};

export function canViewInsights(role?: MembershipRole): boolean {
  return role === "AP_MANAGER" || role === "ORG_ADMIN";
}
