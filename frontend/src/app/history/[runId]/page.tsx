import { RunDetailPage } from "@/components/history/run-detail";

export default async function Page({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <RunDetailPage runId={runId} />;
}
