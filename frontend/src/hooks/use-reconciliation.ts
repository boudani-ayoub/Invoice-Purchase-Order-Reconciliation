"use client";

import { useCallback, useMemo, useState } from "react";

import { ReconciliationRequestError } from "@/lib/api/reconciliation";
import {
  EMPTY_UPLOADS,
  type UploadField,
  type UploadFiles,
} from "@/constants/uploads";
import type { ReconciliationErrorDetail } from "@/types/reconciliation";
import type { AnalysisMode, AnalysisReport } from "@/types/analysis";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { createRun } from "@/lib/api/runs";

function freshUploads(): UploadFiles {
  return { ...EMPTY_UPLOADS };
}

export function useReconciliation(mode?: AnalysisMode) {
  const [files, setFiles] = useState<UploadFiles>(freshUploads);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [savedRunId, setSavedRunId] = useState<string | null>(null);
  const [error, setError] = useState<ReconciliationErrorDetail | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const allFilesSelected = useMemo(
    () =>
      ANALYSIS_MODES[mode ?? "three-way"].requiredSources.every((field) =>
        Boolean(files[field]),
      ),
    [files, mode],
  );

  const setFile = useCallback((field: UploadField, file: File | null) => {
    setFiles((current) => ({ ...current, [field]: file }));
    setReport(null);
    setSavedRunId(null);
    setError(null);
  }, []);

  const submit = useCallback(async () => {
    if (!allFilesSelected || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const saved = await createRun(mode ?? "three-way", files);
      setReport(saved.report);
      setSavedRunId(saved.run.id);
    } catch (caught) {
      setReport(null);
      setSavedRunId(null);
      setError(
        caught instanceof ReconciliationRequestError
          ? caught.detail
          : { kind: "unexpected_response" },
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [allFilesSelected, files, isSubmitting, mode]);

  const reset = useCallback(() => {
    setFiles(freshUploads());
    setReport(null);
    setSavedRunId(null);
    setError(null);
    setIsSubmitting(false);
  }, []);

  return {
    files,
    report,
    savedRunId,
    error,
    isSubmitting,
    canSubmit: allFilesSelected && !isSubmitting,
    setFile,
    submit,
    reset,
  };
}
