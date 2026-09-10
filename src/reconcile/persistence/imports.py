"""Map validated occurrences without inventing master data or financial decisions."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import any_, select
from sqlalchemy.orm import Session

from reconcile.analysis.models import SourceType
from reconcile.models import GoodsReceiptLine, InvoiceLine, PurchaseOrderLine
from reconcile.persistence import models as db

SourceRecord = PurchaseOrderLine | GoodsReceiptLine | InvoiceLine


@dataclass(frozen=True)
class SourceEvidence:
    source_type: SourceType
    filename: str
    size_bytes: int
    sha256: str
    records: tuple[SourceRecord, ...]
    row_numbers: tuple[int, ...]


@dataclass
class EvidenceIndex:
    sources: list[db.SourceFile] = field(default_factory=list)
    orders: dict[tuple[str, int, str], UUID] = field(default_factory=dict)
    receipts: dict[tuple[str, int], UUID] = field(default_factory=dict)
    invoices: dict[tuple[object, ...], deque[UUID]] = field(
        default_factory=lambda: defaultdict(deque)
    )


def invoice_key(row: InvoiceLine) -> tuple[object, ...]:
    return (
        row.supplier_id,
        row.invoice_number,
        row.line_number,
        row.invoice_date.isoformat(),
        row.po_number,
        row.po_line_number,
        row.item_code,
        row.invoiced_quantity,
        row.unit_price,
        row.currency,
    )


def report_invoice_key(row: dict) -> tuple[object, ...]:
    return (
        row["supplier_id"],
        row["invoice_number"],
        row["invoice_line_number"],
        row["invoice_date"],
        row["po_number"],
        row["po_line_number"],
        row["item_code"],
        Decimal(row["current_invoiced_quantity"]),
        Decimal(row["invoice_unit_price"]),
        row["currency"],
    )


def import_sources(
    session: Session, organization: UUID, sources: tuple[SourceEvidence, ...]
) -> EvidenceIndex:
    index = EvidenceIndex()
    records = [row for source in sources for row in source.records]
    supplier_codes = {
        row.supplier_id for row in records if isinstance(row, PurchaseOrderLine | InvoiceLine)
    }
    item_codes = {row.item_code for row in records}
    suppliers = dict(
        session.execute(
            select(db.Supplier.supplier_code, db.Supplier.id).where(
                db.Supplier.organization_id == organization,
                db.Supplier.supplier_code == any_(list(supplier_codes)),
                db.Supplier.status == db.RecordStatus.ACTIVE,
            )
        ).all()
    )
    items = dict(
        session.execute(
            select(db.Item.item_code, db.Item.id).where(
                db.Item.organization_id == organization,
                db.Item.item_code == any_(list(item_codes)),
                db.Item.status == db.RecordStatus.ACTIVE,
            )
        ).all()
    )
    ordered_sources = sorted(sources, key=lambda source: list(SourceType).index(source.source_type))
    for evidence in ordered_sources:
        source = db.SourceFile(
            id=uuid4(),
            organization_id=organization,
            source_type=evidence.source_type,
            original_filename=evidence.filename,
            size_bytes=evidence.size_bytes,
            sha256=evidence.sha256,
        )
        session.add(source)
        session.flush()
        index.sources.append(source)
        headers = {}
        lines = []
        for row_number, row in zip(evidence.row_numbers, evidence.records, strict=True):
            common = dict(
                id=uuid4(),
                organization_id=organization,
                source_row_number=row_number,
                line_number=row.line_number,
                source_item_code=row.item_code,
                resolved_item_id=items.get(row.item_code),
            )
            if isinstance(row, PurchaseOrderLine):
                key = row.po_number
                if key not in headers:
                    headers[key] = db.PurchaseOrder(
                        id=uuid4(),
                        organization_id=organization,
                        source_file_id=source.id,
                        po_number=key,
                        source_supplier_code=row.supplier_id,
                        resolved_supplier_id=suppliers.get(row.supplier_id),
                        order_date=row.order_date,
                        currency=row.currency,
                    )
                line = db.PurchaseOrderLine(
                    **common,
                    purchase_order_id=headers[key].id,
                    description=row.description,
                    ordered_quantity=row.ordered_quantity,
                    unit_price=row.unit_price,
                )
                index.orders[(row.po_number, row.line_number, row.item_code)] = line.id
            else:
                common.update(
                    source_po_number=row.po_number,
                    source_po_line_number=row.po_line_number,
                    resolved_purchase_order_line_id=index.orders.get(
                        (row.po_number, row.po_line_number, row.item_code)
                    ),
                )
                if isinstance(row, GoodsReceiptLine):
                    key = row.receipt_id
                    if key not in headers:
                        headers[key] = db.GoodsReceipt(
                            id=uuid4(),
                            organization_id=organization,
                            source_file_id=source.id,
                            receipt_number=key,
                        )
                    line = db.GoodsReceiptLine(
                        **common,
                        goods_receipt_id=headers[key].id,
                        receipt_date=row.receipt_date,
                        received_quantity=row.received_quantity,
                    )
                    index.receipts[(row.receipt_id, row.line_number)] = line.id
                else:
                    key = (row.supplier_id, row.invoice_number)
                    if key not in headers:
                        headers[key] = db.Invoice(
                            id=uuid4(),
                            organization_id=organization,
                            source_file_id=source.id,
                            invoice_number=row.invoice_number,
                            source_supplier_code=row.supplier_id,
                            resolved_supplier_id=suppliers.get(row.supplier_id),
                            invoice_date=row.invoice_date,
                            currency=row.currency,
                        )
                    line = db.InvoiceLine(
                        **common,
                        invoice_id=headers[key].id,
                        invoiced_quantity=row.invoiced_quantity,
                        unit_price=row.unit_price,
                    )
                    index.invoices[invoice_key(row)].append(line.id)
            lines.append(line)
        session.add_all(headers.values())
        session.flush()
        session.add_all(lines)
        session.flush()
    return index
