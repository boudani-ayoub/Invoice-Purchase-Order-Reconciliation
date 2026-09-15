import type { MembershipRole } from "@/types/auth";

export type MembershipStatus = "ACTIVE" | "ARCHIVED";
export type InvitationStatus = "PENDING" | "ACCEPTED" | "REVOKED";
export type AuditSource = "RUN" | "WORKFLOW" | "GOVERNANCE";

export interface OrganizationSettings {
  id: string;
  name: string;
  version: number;
}

export interface OrganizationMember {
  user_id: string;
  display_name: string;
  email: string;
  role: MembershipRole;
  status: MembershipStatus;
  version: number;
  created_at: string;
}

export interface OrganizationInvitation {
  id: string;
  email: string;
  role: MembershipRole;
  status: InvitationStatus;
  expired: boolean;
  version: number;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface AuditEntry {
  id: string;
  source: AuditSource;
  event_type: string;
  resource_type: string;
  resource_id: string;
  actor_user_id: string;
  actor_display_name: string;
  request_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface InvitationPreview {
  organization_name: string;
  email: string;
  role: MembershipRole;
  expires_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
