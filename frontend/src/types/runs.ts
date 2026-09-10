import type { AnalysisMode, AnalysisReport } from "./analysis";

export interface RunListItem {
  id: string;
  mode: AnalysisMode;
  status: "COMPLETED";
  title: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  version: number;
  created_by_user_id: string | null;
  summary: AnalysisReport["summary"];
}
export interface RunMetadata extends RunListItem {
  note: string | null;
}
export interface RunListResponse {
  items: RunListItem[];
  next_cursor: string | null;
}
export interface SourceProvenance {
  source_type: "purchase_orders" | "receipts" | "invoices";
  filename: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
}
export interface PersistentRunCreateResponse {
  run: RunMetadata;
  report: AnalysisReport;
}
export interface RunDetail extends PersistentRunCreateResponse {
  sources: SourceProvenance[];
  engine_version: string;
  schema_version: number;
}
export interface RunMutation {
  title?: string | null;
  note?: string | null;
  expected_version: number;
}
export interface HistoryQuery {
  mode?: AnalysisMode;
  archived: boolean;
  cursor?: string;
}
