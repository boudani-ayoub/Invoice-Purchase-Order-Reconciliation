import { FindingDetailPage } from "@/components/workflow/finding-detail";

export default async function Page({
  params,
}: {
  params: Promise<{ findingId: string }>;
}) {
  const { findingId } = await params;
  return <FindingDetailPage findingId={findingId} />;
}
