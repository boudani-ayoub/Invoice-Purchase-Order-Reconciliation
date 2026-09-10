"""Index issued report findings; the snapshot remains the authoritative presentation."""

from uuid import UUID

from sqlalchemy.orm import Session

from reconcile.analysis.models import AnalysisMode, FulfillmentStatus
from reconcile.models import IssueCode
from reconcile.persistence.imports import EvidenceIndex, report_invoice_key
from reconcile.persistence.models import Finding, FindingCategory

ISSUE_CATEGORIES = {
    IssueCode.UNKNOWN_PO: FindingCategory.REFERENCE,
    IssueCode.UNKNOWN_ITEM: FindingCategory.REFERENCE,
    IssueCode.RECEIPT_ITEM_MISMATCH: FindingCategory.REFERENCE,
    IssueCode.DUPLICATE_INVOICE: FindingCategory.DUPLICATE,
    IssueCode.SUPPLIER_MISMATCH: FindingCategory.COMMERCIAL,
    IssueCode.CURRENCY_MISMATCH: FindingCategory.COMMERCIAL,
    IssueCode.PRICE_MISMATCH: FindingCategory.COMMERCIAL,
    IssueCode.MISSING_RECEIPT: FindingCategory.QUANTITY,
    IssueCode.QUANTITY_EXCEEDS_PO: FindingCategory.QUANTITY,
    IssueCode.QUANTITY_EXCEEDS_RECEIPT: FindingCategory.QUANTITY,
    IssueCode.OVER_RECEIVED: FindingCategory.QUANTITY,
}


def persist_findings(
    session: Session, organization: UUID, run_id: UUID, report: dict, evidence: EvidenceIndex
) -> None:
    def add(code: IssueCode, **subjects) -> None:
        session.add(
            Finding(
                organization_id=organization,
                analysis_run_id=run_id,
                code=code,
                category=ISSUE_CATEGORIES[code],
                **subjects,
            )
        )

    for row in report["results"]:
        po_id = evidence.orders.get((row["po_number"], row["po_line_number"], row["item_code"]))
        if report["mode"] == AnalysisMode.PO_RECEIPT:
            if row["status"] == FulfillmentStatus.OVER_RECEIVED:
                add(IssueCode.OVER_RECEIVED, purchase_order_line_id=po_id)
        else:
            invoice_id = evidence.invoices[report_invoice_key(row)].popleft()
            for issue in row["issues"]:
                add(IssueCode(issue), invoice_line_id=invoice_id, purchase_order_line_id=po_id)
    for row in report.get("orphan_receipts", []):
        add(
            IssueCode(row["issue"]),
            goods_receipt_line_id=evidence.receipts[
                (row["receipt_id"], row["receipt_line_number"])
            ],
        )
