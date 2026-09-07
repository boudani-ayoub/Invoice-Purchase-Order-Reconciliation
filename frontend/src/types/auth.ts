export type MembershipRole = "MEMBER" | "AP_MANAGER" | "ORG_ADMIN";

export interface Membership {
  organization_id: string;
  organization_name: string;
  role: MembershipRole;
}

export interface AuthSession {
  user: { id: string; email: string; display_name: string };
  memberships: Membership[];
  active_organization_id: string | null;
}

export type AuthAction =
  | "register"
  | "login"
  | "logout"
  | "forgot-password"
  | "reset-password"
  | "verify-email"
  | "resend-verification"
  | "select-organization";
