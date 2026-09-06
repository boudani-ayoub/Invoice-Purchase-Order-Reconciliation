"use client";

import { FileCheck2, FileUp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatFileSize } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import type { UploadField } from "@/constants/uploads";

interface FileInputCardProps {
  field: UploadField;
  label: string;
  actionLabel: string;
  description: string;
  file: File | null;
  disabled: boolean;
  onChange: (field: UploadField, file: File | null) => void;
}

export function FileInputCard({
  field,
  label,
  actionLabel,
  description,
  file,
  disabled,
  onChange,
}: FileInputCardProps) {
  const inputId = `upload-${field}`;

  return (
    <Card
      className={cn(
        "border border-transparent shadow-none transition-colors",
        file ? "bg-success-muted/45 ring-success/25" : "bg-card",
      )}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            {file ? (
              <FileCheck2 aria-hidden="true" className="size-4 text-success" />
            ) : (
              <FileUp aria-hidden="true" className="size-4" />
            )}
          </div>
          <span className="text-xs font-medium text-muted-foreground">
            {file ? "Selected" : "Required"}
          </span>
        </div>
        <CardTitle className="mt-2">{label}</CardTitle>
        <CardDescription className="min-h-10 leading-5">{description}</CardDescription>
      </CardHeader>
      <CardContent className="mt-auto space-y-3">
        {file ? (
          <div className="rounded-lg border bg-background px-3 py-2" aria-live="polite">
            <p className="truncate text-sm font-medium" title={file.name}>
              {file.name}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground">
            No file selected
          </p>
        )}

        <div className="flex items-center gap-2">
          <input
            key={file ? `${file.name}-${file.lastModified}` : "empty"}
            id={inputId}
            type="file"
            accept=".csv,text/csv"
            className="peer sr-only"
            disabled={disabled}
            aria-label={actionLabel}
            onChange={(event) => onChange(field, event.target.files?.[0] ?? null)}
          />
          <Button
            asChild
            variant="outline"
            aria-disabled={disabled}
            className={cn(
              "peer-focus-visible:border-ring peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50",
              disabled && "pointer-events-none opacity-50",
            )}
          >
            <label htmlFor={inputId}>{file ? "Replace file" : actionLabel}</label>
          </Button>
          {file ? (
            <Button
              type="button"
              variant="ghost"
              disabled={disabled}
              onClick={() => onChange(field, null)}
            >
              <X aria-hidden="true" data-icon="inline-start" />
              Remove
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
