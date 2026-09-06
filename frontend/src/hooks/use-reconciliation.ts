"use client";

import { useCallback, useMemo, useState } from "react";

import {
  ReconciliationRequestError,
  reconcileFiles,
} from "@/lib/api/reconciliation";
import {
  EMPTY_UPLOADS,
  type UploadField,
  type UploadFiles,
} from "@/constants/uploads";
import type { ReconciliationErrorDetail } from "@/types/reconciliation";
import type { AnalysisMode, AnalysisReport } from "@/types/analysis";
import { ANALYSIS_MODES } from "@/constants/analysis-modes";
import { analyzeFiles } from "@/lib/api/analyses";

function freshUploads(): UploadFiles {
  return { ...EMPTY_UPLOADS };
}

export function useReconciliation(mode?: AnalysisMode) {
  const [files, setFiles] = useState<UploadFiles>(freshUploads);
  const [report, setReport] = useState<AnalysisReport | null>(null);
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
    setError(null);
  }, []);

  const submit = useCallback(async () => {
    if (!allFilesSelected || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      setReport(
        mode
          ? await analyzeFiles(mode, files)
          : { ...(await reconcileFiles(files)), mode: "three-way" },
      );
    } catch (caught) {
      setReport(null);
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
    setError(null);
    setIsSubmitting(false);
  }, []);

  return {
    files,
    report,
    error,
    isSubmitting,
    canSubmit: allFilesSelected && !isSubmitting,
    setFile,
    submit,
    reset,
  };
}
