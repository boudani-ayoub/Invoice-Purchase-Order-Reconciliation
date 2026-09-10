import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AnalysisHub } from "./analysis-hub";
import { ReconciliationWorkspace } from "./reconciliation-workspace";
import { ANALYSIS_MODES, analysisPath } from "@/constants/analysis-modes";
import { UPLOAD_SOURCES } from "@/constants/uploads";
import { createRun } from "@/lib/api/runs";
import { savedRun } from "@/test/fixtures/runs";
import { ReconciliationRequestError } from "@/lib/api/reconciliation";
import { ANALYSIS_REPORTS } from "@/test/fixtures/analyses";

vi.mock("@/lib/api/runs", () => ({ createRun: vi.fn() }));
const mockedAnalyze = vi.mocked(createRun);
beforeEach(() => mockedAnalyze.mockReset());

it("links the four hub choices to bookmarkable routes", () => {
  render(<AnalysisHub />);
  expect(screen.getAllByRole("link")).toHaveLength(4);
  for (const mode of Object.values(ANALYSIS_MODES)) {
    expect(
      screen.getByRole("link", { name: new RegExp(mode.title) }),
    ).toHaveAttribute("href", analysisPath(mode.id));
  }
});

for (const report of ANALYSIS_REPORTS) {
  const definition = ANALYSIS_MODES[report.mode];
  it(`${report.mode} requires only its sources, presents its results, and resets`, async () => {
    mockedAnalyze.mockResolvedValue(savedRun(report));
    const user = userEvent.setup();
    render(<ReconciliationWorkspace mode={report.mode} />);
    expect(screen.getByText(definition.limitations)).toBeVisible();
    const submit = screen.getByRole("button", { name: definition.submitLabel });
    expect(submit).toBeDisabled();
    for (const source of UPLOAD_SOURCES) {
      if (definition.requiredSources.includes(source.field)) {
        await user.upload(
          screen.getByLabelText(source.actionLabel),
          new File(["csv"], `${source.field}.csv`, { type: "text/csv" }),
        );
      } else {
        expect(
          screen.queryByLabelText(source.actionLabel),
        ).not.toBeInTheDocument();
      }
    }
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(
      await screen.findByRole("heading", { name: definition.resultTitle }),
    ).toBeVisible();
    expect(mockedAnalyze).toHaveBeenCalledWith(report.mode, expect.any(Object));
    if (report.mode === "po-receipt") {
      expect(screen.getByText("Outstanding ordered value")).toBeVisible();
      expect(screen.getByText("ORPHAN / 1")).toBeVisible();
      expect(
        screen.queryByText("Potential disputed amount"),
      ).not.toBeInTheDocument();
    } else if (report.mode === "invoice-receipt") {
      expect(
        screen.getByText("Potential unsupported invoice amount"),
      ).toBeVisible();
      expect(
        screen.queryByRole("columnheader", { name: "Invoice / PO price" }),
      ).not.toBeInTheDocument();
    }
    await user.click(
      screen.getByRole("button", {
        name:
          report.mode === "po-receipt"
            ? "Start new analysis"
            : "Start new reconciliation",
      }),
    );
    expect(submit).toBeDisabled();
    expect(
      screen.queryByRole("heading", { name: definition.resultTitle }),
    ).not.toBeInTheDocument();
  });
}

it("keeps two-file errors readable and permits retry", async () => {
  mockedAnalyze.mockRejectedValueOnce(
    new ReconciliationRequestError({ kind: "network" }),
  );
  mockedAnalyze.mockResolvedValueOnce(savedRun(ANALYSIS_REPORTS[0]));
  const user = userEvent.setup();
  render(<ReconciliationWorkspace mode="invoice-po" />);
  for (const label of ["Choose purchase orders", "Choose invoices"]) {
    await user.upload(
      screen.getByLabelText(label),
      new File(["csv"], "source.csv", { type: "text/csv" }),
    );
  }
  await user.click(screen.getByRole("button", { name: "Run invoice match" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByRole("heading", {
      name: "Invoice vs Purchase Order results",
    }),
  ).toBeVisible();
});
