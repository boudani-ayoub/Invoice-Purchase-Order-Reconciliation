import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { UPLOAD_FIELD_LABELS, type UploadField } from "@/constants/uploads";
import type { CsvValidationIssue } from "@/types/reconciliation";

interface ValidationIssuesProps {
  issues: CsvValidationIssue[];
}

function isUploadField(value: string): value is UploadField {
  return value in UPLOAD_FIELD_LABELS;
}

function sourceLabel(issue: CsvValidationIssue): string {
  return isUploadField(issue.file) ? UPLOAD_FIELD_LABELS[issue.file] : issue.source;
}

export function ValidationIssues({ issues }: ValidationIssuesProps) {
  const grouped = new Map<string, CsvValidationIssue[]>();
  for (const issue of issues) {
    const source = sourceLabel(issue);
    grouped.set(source, [...(grouped.get(source) ?? []), issue]);
  }

  return (
    <Alert variant="destructive" aria-live="assertive" className="px-4 py-4">
      <AlertCircle aria-hidden="true" />
      <AlertTitle>Some CSV data could not be processed</AlertTitle>
      <AlertDescription className="mt-2 space-y-4">
        {[...grouped].map(([source, sourceIssues]) => (
          <section key={source} aria-label={`${source} validation issues`}>
            <h3 className="font-medium text-foreground">{source}</h3>
            <ul className="mt-2 space-y-2">
              {sourceIssues.map((issue, index) => (
                <li
                  key={`${issue.row}-${issue.column}-${index}`}
                  className="rounded-lg border border-destructive/20 bg-background px-3 py-2 text-foreground"
                >
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>{issue.row === null ? "File-level issue" : `Row ${issue.row}`}</span>
                    <span>Column: {issue.column}</span>
                    <span>Value: {issue.value || "Empty"}</span>
                  </div>
                  <p className="mt-1 text-sm">{issue.reason}</p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </AlertDescription>
    </Alert>
  );
}
