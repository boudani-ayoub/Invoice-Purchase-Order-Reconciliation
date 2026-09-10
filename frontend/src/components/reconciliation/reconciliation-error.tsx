import { AlertTriangle, ServerCrash, Unplug } from "lucide-react";

import { ValidationIssues } from "@/components/reconciliation/validation-issues";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { UPLOAD_FIELD_LABELS, type UploadField } from "@/constants/uploads";
import { formatFileSize } from "@/lib/formatters";
import type { ReconciliationErrorDetail } from "@/types/reconciliation";

interface ReconciliationErrorProps {
  error: ReconciliationErrorDetail;
  onRetry: () => void;
}

function fieldLabel(field: string): string {
  return field in UPLOAD_FIELD_LABELS
    ? UPLOAD_FIELD_LABELS[field as UploadField]
    : field.replaceAll("_", " ");
}

export function ReconciliationError({
  error,
  onRetry,
}: ReconciliationErrorProps) {
  if (error.kind === "validation") {
    return <ValidationIssues issues={error.issues} />;
  }

  if (error.kind === "file_too_large") {
    return (
      <Alert variant="destructive" aria-live="assertive" className="px-4 py-4">
        <AlertTriangle aria-hidden="true" />
        <AlertTitle>{fieldLabel(error.file)} file is too large</AlertTitle>
        <AlertDescription>
          Choose a file no larger than {formatFileSize(error.maxBytes)}, then
          run the reconciliation again.
        </AlertDescription>
      </Alert>
    );
  }

  if (error.kind === "missing_upload") {
    const labels = error.fields.map(fieldLabel);
    return (
      <Alert variant="destructive" aria-live="assertive" className="px-4 py-4">
        <AlertTriangle aria-hidden="true" />
        <AlertTitle>All three source files are required</AlertTitle>
        <AlertDescription>
          Select {labels.length ? labels.join(", ") : "the missing source file"}{" "}
          and try again.
        </AlertDescription>
      </Alert>
    );
  }

  const content =
    error.kind === "storage_capacity"
      ? {
          icon: AlertTriangle,
          title: "These source values cannot be saved",
          message:
            "A value exceeds the database's supported range or encoding. No run was saved. Review the source values before resubmitting.",
        }
      : error.kind === "authorization"
        ? {
            icon: AlertTriangle,
            title: "Your access could not be verified",
            message:
              "Check your session and organization, then try again. If access was revoked, contact your administrator.",
          }
        : error.kind === "network"
          ? {
              icon: Unplug,
              title: "The reconciliation service could not be reached",
              message:
                "Check your connection and History before retrying. A lost response may still have saved a run.",
            }
          : error.kind === "timeout"
            ? {
                icon: Unplug,
                title: "The reconciliation request timed out",
                message:
                  "The service may still finish saving this run. Check History before retrying; another submission creates a separate run.",
              }
            : error.kind === "server"
              ? {
                  icon: ServerCrash,
                  title:
                    "Something went wrong while processing the reconciliation",
                  message:
                    "The service did not confirm a saved result. Check History before retrying.",
                }
              : {
                  icon: AlertTriangle,
                  title: "The service returned an unexpected response",
                  message:
                    "The saved result could not be confirmed. Check History and the API configuration before retrying.",
                };
  const Icon = content.icon;

  return (
    <Alert variant="destructive" aria-live="assertive" className="px-4 py-4">
      <Icon aria-hidden="true" />
      <AlertTitle>{content.title}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>{content.message}</span>
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </AlertDescription>
    </Alert>
  );
}
