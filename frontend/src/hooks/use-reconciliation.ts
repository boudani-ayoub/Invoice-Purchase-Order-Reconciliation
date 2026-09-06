"use client";

import { useCallback, useMemo, useState } from "react";

import {
  ReconciliationRequestError,
  reconcileFiles,
} from "@/lib/api/reconciliation";
import { EMPTY_UPLOADS, type UploadField, type UploadFiles } from "@/constants/uploads";
import type { ReconciliationErrorDetail, ReconciliationReport } from "@/types/reconciliation";

function freshUploads(): UploadFiles {
  return { ...EMPTY_UPLOADS };
}

export function useReconciliation() {
  const [files, setFiles] = useState<UploadFiles>(freshUploads);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [error, setError] = useState<ReconciliationErrorDetail | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const allFilesSelected = useMemo(() => Object.values(files).every(Boolean), [files]);

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
      setReport(await reconcileFiles(files));
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
  }, [allFilesSelected, files, isSubmitting]);

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
