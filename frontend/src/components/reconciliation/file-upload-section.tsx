"use client";

import { LoaderCircle, LockKeyhole } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FileInputCard } from "@/components/reconciliation/file-input-card";
import {
  UPLOAD_SOURCES,
  type UploadField,
  type UploadFiles,
} from "@/constants/uploads";
import {
  ANALYSIS_MODES,
  type AnalysisModeDefinition,
} from "@/constants/analysis-modes";

interface FileUploadSectionProps {
  files: UploadFiles;
  canSubmit: boolean;
  isSubmitting: boolean;
  onFileChange: (field: UploadField, file: File | null) => void;
  onSubmit: () => void;
  definition?: AnalysisModeDefinition;
}

export function FileUploadSection({
  files,
  canSubmit,
  isSubmitting,
  onFileChange,
  onSubmit,
  definition = ANALYSIS_MODES["three-way"],
}: FileUploadSectionProps) {
  return (
    <section aria-labelledby="upload-heading" className="space-y-5">
      <div>
        <p className="text-xs font-semibold tracking-wider text-primary uppercase">
          Input files
        </p>
        <h2
          id="upload-heading"
          className="mt-1 text-xl font-semibold tracking-tight"
        >
          {definition.requiredSources.length === 3
            ? "Choose the three source exports"
            : "Choose the two source exports"}
        </h2>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          Select one CSV for each source. File contents are validated by the
          reconciliation service.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {UPLOAD_SOURCES.filter((source) =>
          definition.requiredSources.includes(source.field),
        ).map((source) => (
          <FileInputCard
            key={source.field}
            {...source}
            file={files[source.field]}
            disabled={isSubmitting}
            onChange={onFileChange}
          />
        ))}
      </div>

      <div className="flex flex-col gap-4 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex max-w-xl items-start gap-2 text-sm text-muted-foreground">
          <LockKeyhole
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-primary"
          />
          <p>
            Files are processed for this request and are not stored by the
            current service.
          </p>
        </div>
        <Button
          type="button"
          size="lg"
          className="min-w-44"
          disabled={!canSubmit}
          aria-describedby="reconciliation-status"
          onClick={onSubmit}
        >
          {isSubmitting ? (
            <>
              <LoaderCircle
                aria-hidden="true"
                className="animate-spin"
                data-icon="inline-start"
              />
              Reconciling…
            </>
          ) : (
            definition.submitLabel
          )}
        </Button>
      </div>
      <p id="reconciliation-status" className="sr-only" aria-live="polite">
        {isSubmitting ? "Reconciliation is in progress." : ""}
      </p>
    </section>
  );
}
