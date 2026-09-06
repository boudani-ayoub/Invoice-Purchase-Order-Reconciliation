import { notFound } from "next/navigation";
import { ReconciliationWorkspace } from "@/components/reconciliation/reconciliation-workspace";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";

export function generateStaticParams() {
  return Object.keys(ANALYSIS_MODES).map((mode) => ({ mode }));
}

export default async function WorkflowPage({
  params,
}: {
  params: Promise<{ mode: string }>;
}) {
  const { mode } = await params;
  const definition = Object.values(ANALYSIS_MODES).find(
    (entry) => entry.id === mode,
  );
  if (!definition) notFound();
  return <ReconciliationWorkspace key={definition.id} mode={definition.id} />;
}
