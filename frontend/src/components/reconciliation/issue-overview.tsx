import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getIssuePresentation } from "@/constants/issues";

interface IssueOverviewProps {
  issueCounts: Record<string, number>;
}

export function IssueOverview({ issueCounts }: IssueOverviewProps) {
  const issues = Object.entries(issueCounts).sort(
    ([leftCode, leftCount], [rightCode, rightCount]) =>
      rightCount - leftCount ||
      getIssuePresentation(leftCode).label.localeCompare(getIssuePresentation(rightCode).label),
  );

  return (
    <Card className="shadow-none lg:col-span-2">
      <CardHeader>
        <CardTitle>Issue overview</CardTitle>
      </CardHeader>
      <CardContent>
        {issues.length ? (
          <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {issues.map(([code, count]) => {
              const presentation = getIssuePresentation(code);
              return (
                <li key={code} className="flex items-center justify-between gap-3 border-b py-2 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
                  <span className="text-sm">{presentation.label}</span>
                  <Badge variant="secondary" className="tabular-nums">
                    {count}
                  </Badge>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No issues recorded.</p>
        )}
      </CardContent>
    </Card>
  );
}
