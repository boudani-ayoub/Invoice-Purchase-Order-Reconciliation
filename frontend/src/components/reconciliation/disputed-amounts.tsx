import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDecimalString } from "@/lib/formatters";

interface DisputedAmountsProps {
  amounts: Record<string, string>;
}

export function DisputedAmounts({ amounts }: DisputedAmountsProps) {
  const entries = Object.entries(amounts).sort(([left], [right]) => left.localeCompare(right));

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>Potential disputed amount</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length ? (
          <dl className="divide-y">
            {entries.map(([currency, amount]) => (
              <div key={currency} className="flex items-baseline justify-between gap-4 py-3 first:pt-0 last:pb-0">
                <dt className="text-sm font-medium text-muted-foreground">{currency}</dt>
                <dd className="font-mono text-lg font-semibold tabular-nums">
                  {formatDecimalString(amount)}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">No disputed amounts.</p>
        )}
      </CardContent>
    </Card>
  );
}
