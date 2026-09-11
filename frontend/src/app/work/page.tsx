import { WorkQueue } from "@/components/workflow/work-queue";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ run_id?: string | string[] }>;
}) {
  const { run_id } = await searchParams;
  const runId = typeof run_id === "string" ? run_id : undefined;
  return <WorkQueue key={runId ?? "all"} runId={runId} />;
}
