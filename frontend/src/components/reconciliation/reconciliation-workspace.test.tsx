import { render, screen, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReconciliationWorkspace } from "@/components/reconciliation/reconciliation-workspace";
import { ReconciliationRequestError } from "@/lib/api/reconciliation";
import { RECONCILIATION_REPORT_FIXTURE } from "@/test/fixtures/reconciliation";
import type { ReconciliationErrorDetail } from "@/types/reconciliation";
import { createRun } from "@/lib/api/runs";
import { savedRun } from "@/test/fixtures/runs";
import type { PersistentRunCreateResponse } from "@/types/runs";

vi.mock("@/lib/api/runs", () => ({ createRun: vi.fn() }));

const mockedReconcileFiles = vi.mocked(createRun);
const SAVED_REPORT = savedRun({
  ...RECONCILIATION_REPORT_FIXTURE,
  mode: "three-way",
});

async function selectAllFiles(user: UserEvent) {
  await user.upload(
    screen.getByLabelText("Choose purchase orders"),
    new File(["purchase orders"], "purchase_orders.csv", { type: "text/csv" }),
  );
  await user.upload(
    screen.getByLabelText("Choose goods receipts"),
    new File(["receipts"], "goods_receipts.csv", { type: "text/csv" }),
  );
  await user.upload(
    screen.getByLabelText("Choose invoices"),
    new File(["invoices"], "invoices.csv", { type: "text/csv" }),
  );
}

async function submitWithAllFiles(user: UserEvent) {
  await selectAllFiles(user);
  await user.click(screen.getByRole("button", { name: "Run reconciliation" }));
}

function apiError(
  detail: ReconciliationErrorDetail,
): ReconciliationRequestError {
  return new ReconciliationRequestError(detail);
}

beforeEach(() => {
  mockedReconcileFiles.mockReset();
});

describe("ReconciliationWorkspace", () => {
  it("renders three required file controls and enables submission only when ready", async () => {
    const user = userEvent.setup();
    render(<ReconciliationWorkspace />);

    const submit = screen.getByRole("button", { name: "Run reconciliation" });
    expect(screen.getByLabelText("Choose purchase orders")).toBeInTheDocument();
    expect(screen.getByLabelText("Choose goods receipts")).toBeInTheDocument();
    expect(screen.getByLabelText("Choose invoices")).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await selectAllFiles(user);

    expect(submit).toBeEnabled();
    expect(screen.getByText("purchase_orders.csv")).toBeInTheDocument();
    expect(screen.getByText("goods_receipts.csv")).toBeInTheDocument();
    expect(screen.getByText("invoices.csv")).toBeInTheDocument();
  });

  it("prevents duplicate submission and announces loading", async () => {
    const user = userEvent.setup();
    let finishRequest:
      ((value: PersistentRunCreateResponse) => void) | undefined;
    mockedReconcileFiles.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishRequest = resolve;
        }),
    );
    render(<ReconciliationWorkspace />);

    await submitWithAllFiles(user);

    const loadingButton = screen.getByRole("button", { name: "Reconciling…" });
    expect(loadingButton).toBeDisabled();
    expect(
      screen.getByText("Reconciliation is in progress."),
    ).toBeInTheDocument();
    await user.click(loadingButton);
    expect(mockedReconcileFiles).toHaveBeenCalledOnce();

    finishRequest?.(SAVED_REPORT);
    expect(
      await screen.findByRole("heading", { name: "Reconciliation results" }),
    ).toBeInTheDocument();
  });

  it("renders authoritative summary, issue counts, disputed amounts, and results", async () => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockResolvedValue(SAVED_REPORT);
    render(<ReconciliationWorkspace />);

    await submitWithAllFiles(user);

    const resultsHeading = await screen.findByRole("heading", {
      name: "Reconciliation results",
    });
    expect(resultsHeading).toHaveFocus();
    expect(
      screen.getByText("Invoices processed").parentElement,
    ).toHaveTextContent("15");
    expect(screen.getByText("Invoice lines").parentElement).toHaveTextContent(
      "17",
    );
    expect(
      screen.getByText("Matched", { selector: "p" }).parentElement,
    ).toHaveTextContent("6");
    expect(
      screen.getByText("Review required", { selector: "p" }).parentElement,
    ).toHaveTextContent("11");
    expect(screen.getByText("10,199.00")).toBeInTheDocument();
    expect(screen.getByText("2,450.00")).toBeInTheDocument();
    expect(screen.getAllByText("Price mismatch")).not.toHaveLength(0);
    expect(screen.getByText("INV-003")).toBeInTheDocument();
  });

  it("focuses review items by default and supports status and issue filtering", async () => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockResolvedValue(SAVED_REPORT);
    render(<ReconciliationWorkspace />);
    await submitWithAllFiles(user);
    await screen.findByRole("heading", { name: "Reconciliation results" });

    expect(screen.queryByText("INV-001")).not.toBeInTheDocument();
    expect(screen.getByText("INV-002")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Matched" }));
    expect(screen.getByText("INV-001")).toBeInTheDocument();
    expect(screen.queryByText("INV-002")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Review required" }));
    await user.click(screen.getByRole("combobox", { name: "Filter by issue" }));
    await user.click(screen.getByRole("option", { name: "Price mismatch" }));
    expect(screen.getByText("INV-003")).toBeInTheDocument();
    expect(screen.queryByText("INV-002")).not.toBeInTheDocument();
  });

  it("presents structured CSV validation details in human-readable form", async () => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockRejectedValue(
      apiError({
        kind: "validation",
        message: "Uploaded CSV data failed validation.",
        issues: [
          {
            file: "purchase_orders",
            source: "purchase_orders.csv",
            row: 2,
            column: "ordered_quantity",
            value: "-3",
            reason:
              "ordered_quantity must be a finite decimal greater than zero",
          },
        ],
      }),
    );
    render(<ReconciliationWorkspace />);

    await submitWithAllFiles(user);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Purchase orders")).toBeInTheDocument();
    expect(within(alert).getByText("Row 2")).toBeInTheDocument();
    expect(
      within(alert).getByText("Column: ordered_quantity"),
    ).toBeInTheDocument();
    expect(within(alert).getByText("Value: -3")).toBeInTheDocument();
    expect(alert).toHaveTextContent(
      "must be a finite decimal greater than zero",
    );
  });

  it("explains an oversized upload using the backend file and limit", async () => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockRejectedValue(
      apiError({
        kind: "file_too_large",
        file: "invoices",
        maxBytes: 10 * 1024 * 1024,
      }),
    );
    render(<ReconciliationWorkspace />);

    await submitWithAllFiles(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Invoices file is too large");
    expect(alert).toHaveTextContent("10.0 MB");
  });

  it.each([
    [
      { kind: "network" } as const,
      "The reconciliation service could not be reached",
      "Check your connection and History before retrying. A lost response may still have saved a run.",
    ],
    [
      { kind: "timeout" } as const,
      "The reconciliation request timed out",
        "The service may still finish saving this run. Check History before retrying; another submission creates a separate run.",
    ],
    [
      { kind: "server" } as const,
      "Something went wrong while processing the reconciliation",
      "The service did not confirm a saved result. Check History before retrying.",
    ],
  ])("shows a safe %s message", async (detail, title, message) => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockRejectedValue(apiError(detail));
    render(<ReconciliationWorkspace />);

    await submitWithAllFiles(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent(message);
    expect(
      within(alert).getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("starts a new reconciliation without reloading the page", async () => {
    const user = userEvent.setup();
    mockedReconcileFiles.mockResolvedValue(SAVED_REPORT);
    render(<ReconciliationWorkspace />);
    await submitWithAllFiles(user);
    await screen.findByRole("heading", { name: "Reconciliation results" });

    await user.click(
      screen.getByRole("button", { name: "Start new reconciliation" }),
    );

    expect(
      screen.queryByRole("heading", { name: "Reconciliation results" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("No file selected")).toHaveLength(3);
    expect(
      screen.getByRole("button", { name: "Run reconciliation" }),
    ).toBeDisabled();
  });
});
