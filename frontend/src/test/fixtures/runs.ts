import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import type { AnalysisReport } from "@/types/analysis";
import type { RunDetail } from "@/types/runs";

export function savedRun(report: AnalysisReport): RunDetail {
  const created = "2026-09-08T12:30:00+00:00";
  return {
    run: {
      id: "142ba884-b6ea-4b64-bf3a-2bd49e502b4a",
      mode: report.mode,
      status: "COMPLETED",
      title: null,
      note: null,
      created_at: created,
      updated_at: created,
      archived_at: null,
      version: 1,
      created_by_user_id: "actor",
      summary: report.summary,
    },
    report,
    engine_version: "0.1.0",
    schema_version: 1,
    sources: ANALYSIS_MODES[report.mode].requiredSources.map((source_type) => ({
      source_type,
      filename: `${source_type}.csv`,
      size_bytes: 100,
      sha256: "a".repeat(64),
      created_at: created,
    })),
  };
}
