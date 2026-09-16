import type { Metadata } from "next";
import { InsightsPage } from "@/components/intelligence/insights-page";

export const metadata: Metadata = { title: "Insights" };

export default function Page() {
  return <InsightsPage />;
}
