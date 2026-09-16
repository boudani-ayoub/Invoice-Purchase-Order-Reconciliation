"""Selected-run procurement and current-ledger inventory intelligence."""

from collections import defaultdict
from datetime import UTC
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, union_all

from reconcile.analysis.models import AnalysisMode, FulfillmentStatus, SourceType
from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence import models as db
from reconcile.persistence.findings import ISSUE_CATEGORIES
from reconcile.persistence.intelligence_policy import (
    INTELLIGENCE_PAGE_MAX,
    INTELLIGENCE_PAGE_SIZE,
    IntelligenceWindow,
    Period,
    decode_cursor,
    encode_cursor,
)


def decimal_string(value: Decimal | int) -> str:
    return format(Decimal(value), "f")


def median(values: list[int]) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    value = (
        Decimal(ordered[middle])
        if len(ordered) % 2
        else (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / 2
    )
    return decimal_string(value)


def fulfillment_status(ordered: Decimal, received: Decimal) -> FulfillmentStatus:
    if received == 0:
        return FulfillmentStatus.NOT_RECEIVED
    if received < ordered:
        return FulfillmentStatus.PARTIALLY_RECEIVED
    if received > ordered:
        return FulfillmentStatus.OVER_RECEIVED
    return FulfillmentStatus.FULLY_RECEIVED


def snapshot_fulfillment(row: dict[str, object], mode: AnalysisMode) -> FulfillmentStatus | None:
    if mode == AnalysisMode.PO_RECEIPT:
        try:
            return FulfillmentStatus(row["status"])
        except (KeyError, ValueError):
            return None
    if mode == AnalysisMode.THREE_WAY:
        try:
            if row.get("ordered_quantity") is None or row.get("received_quantity") is None:
                return None
            return fulfillment_status(
                Decimal(str(row["ordered_quantity"])),
                Decimal(str(row["received_quantity"])),
            )
        except (InvalidOperation, KeyError, ValueError):
            return None
    return None


class Intelligence:
    def __init__(self, sessions: Sessions) -> None:
        self.sessions = sessions

    @staticmethod
    def _selected_run(session, organization: UUID, run_id: UUID):
        found = session.execute(
            select(db.AnalysisRun, db.ResultSnapshot)
            .join(
                db.ResultSnapshot,
                (db.ResultSnapshot.organization_id == db.AnalysisRun.organization_id)
                & (db.ResultSnapshot.analysis_run_id == db.AnalysisRun.id),
            )
            .where(
                db.AnalysisRun.organization_id == organization,
                db.AnalysisRun.id == run_id,
                db.AnalysisRun.status == db.RunStatus.COMPLETED,
            )
        ).first()
        if found is None:
            raise AuthError(404, "not_found", "Completed run not found.")
        run, snapshot = found
        sources = dict(
            session.execute(
                select(db.SourceFile.source_type, db.SourceFile.id)
                .join(
                    db.AnalysisSource,
                    (db.AnalysisSource.organization_id == db.SourceFile.organization_id)
                    & (db.AnalysisSource.source_file_id == db.SourceFile.id),
                )
                .where(
                    db.AnalysisSource.organization_id == organization,
                    db.AnalysisSource.analysis_run_id == run.id,
                )
            ).all()
        )
        return run, snapshot, sources

    @staticmethod
    def _money(session, organization: UUID, sources: dict[SourceType, UUID]):
        ordered = None
        purchase_source = sources.get(SourceType.PURCHASE_ORDERS)
        if purchase_source:
            ordered = {
                currency: decimal_string(value)
                for currency, value in session.execute(
                    select(
                        db.PurchaseOrder.currency,
                        func.sum(
                            db.PurchaseOrderLine.ordered_quantity * db.PurchaseOrderLine.unit_price
                        ),
                    )
                    .join(
                        db.PurchaseOrderLine,
                        (db.PurchaseOrderLine.organization_id == db.PurchaseOrder.organization_id)
                        & (db.PurchaseOrderLine.purchase_order_id == db.PurchaseOrder.id),
                    )
                    .where(
                        db.PurchaseOrder.organization_id == organization,
                        db.PurchaseOrder.source_file_id == purchase_source,
                    )
                    .group_by(db.PurchaseOrder.currency)
                    .order_by(db.PurchaseOrder.currency)
                )
            }
        invoiced = None
        invoice_source = sources.get(SourceType.INVOICES)
        if invoice_source:
            invoiced = {
                currency: decimal_string(value)
                for currency, value in session.execute(
                    select(
                        db.Invoice.currency,
                        func.sum(db.InvoiceLine.invoiced_quantity * db.InvoiceLine.unit_price),
                    )
                    .join(
                        db.InvoiceLine,
                        (db.InvoiceLine.organization_id == db.Invoice.organization_id)
                        & (db.InvoiceLine.invoice_id == db.Invoice.id),
                    )
                    .where(
                        db.Invoice.organization_id == organization,
                        db.Invoice.source_file_id == invoice_source,
                    )
                    .group_by(db.Invoice.currency)
                    .order_by(db.Invoice.currency)
                )
            }
        return ordered, invoiced

    @staticmethod
    def _document_counts(session, organization: UUID, sources: dict[SourceType, UUID]):
        definitions = (
            (
                "purchase_orders",
                SourceType.PURCHASE_ORDERS,
                db.PurchaseOrder,
                db.PurchaseOrderLine,
                db.PurchaseOrderLine.purchase_order_id,
            ),
            (
                "goods_receipts",
                SourceType.RECEIPTS,
                db.GoodsReceipt,
                db.GoodsReceiptLine,
                db.GoodsReceiptLine.goods_receipt_id,
            ),
            (
                "invoices",
                SourceType.INVOICES,
                db.Invoice,
                db.InvoiceLine,
                db.InvoiceLine.invoice_id,
            ),
        )
        documents, lines = {}, {}
        for name, source_type, header, line, line_header_id in definitions:
            source_id = sources.get(source_type)
            if source_id is None:
                documents[name] = None
                lines[name] = None
                continue
            row = session.execute(
                select(func.count(func.distinct(header.id)), func.count(line.id))
                .select_from(header)
                .outerjoin(
                    line,
                    (line.organization_id == header.organization_id)
                    & (line_header_id == header.id),
                )
                .where(header.organization_id == organization, header.source_file_id == source_id)
            ).one()
            documents[name], lines[name] = int(row[0]), int(row[1])
        return documents, lines

    @staticmethod
    def _source_fulfillment_rows(
        session,
        organization: UUID,
        purchase_source: UUID,
        receipt_source: UUID,
        supplier_codes: list[str] | None = None,
    ):
        received = (
            select(
                db.GoodsReceiptLine.resolved_purchase_order_line_id.label("po_line_id"),
                func.sum(db.GoodsReceiptLine.received_quantity).label("received_quantity"),
            )
            .join(
                db.GoodsReceipt,
                (db.GoodsReceipt.organization_id == db.GoodsReceiptLine.organization_id)
                & (db.GoodsReceipt.id == db.GoodsReceiptLine.goods_receipt_id),
            )
            .where(
                db.GoodsReceiptLine.organization_id == organization,
                db.GoodsReceipt.source_file_id == receipt_source,
                db.GoodsReceiptLine.resolved_purchase_order_line_id.is_not(None),
            )
            .group_by(db.GoodsReceiptLine.resolved_purchase_order_line_id)
            .subquery()
        )
        query = (
            select(
                db.PurchaseOrder.source_supplier_code,
                db.PurchaseOrderLine.ordered_quantity,
                func.coalesce(received.c.received_quantity, 0),
            )
            .join(
                db.PurchaseOrderLine,
                (db.PurchaseOrderLine.organization_id == db.PurchaseOrder.organization_id)
                & (db.PurchaseOrderLine.purchase_order_id == db.PurchaseOrder.id),
            )
            .outerjoin(received, received.c.po_line_id == db.PurchaseOrderLine.id)
            .where(
                db.PurchaseOrder.organization_id == organization,
                db.PurchaseOrder.source_file_id == purchase_source,
            )
        )
        if supplier_codes is not None:
            query = query.where(db.PurchaseOrder.source_supplier_code.in_(supplier_codes))
        return session.execute(query).all()

    def procurement(self, raw: str | None, run_id: UUID) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INTELLIGENCE) as (
            principal,
            session,
        ):
            organization = principal.active_organization_id
            run, snapshot, sources = self._selected_run(session, organization, run_id)
            documents, lines = self._document_counts(session, organization, sources)
            ordered, invoiced = self._money(session, organization, sources)
            summary = snapshot.report["summary"]
            issue_counts = {
                str(code): int(count) for code, count in summary.get("issue_counts", {}).items()
            }
            category_counts = {
                category.value: int(count)
                for category, count in session.execute(
                    select(db.Finding.category, func.count())
                    .where(
                        db.Finding.organization_id == organization,
                        db.Finding.analysis_run_id == run.id,
                    )
                    .group_by(db.Finding.category)
                    .order_by(db.Finding.category)
                )
            }
            purchase_source = sources.get(SourceType.PURCHASE_ORDERS)
            receipt_source = sources.get(SourceType.RECEIPTS)
            fulfillment = None
            if purchase_source and receipt_source:
                fulfillment = {status.value: 0 for status in FulfillmentStatus}
                if run.analysis_mode == AnalysisMode.PO_RECEIPT:
                    for row in snapshot.report.get("results", []):
                        status = snapshot_fulfillment(row, run.analysis_mode)
                        if status is not None:
                            fulfillment[status.value] += 1
                else:
                    for _, ordered_quantity, received_quantity in self._source_fulfillment_rows(
                        session, organization, purchase_source, receipt_source
                    ):
                        fulfillment[
                            fulfillment_status(ordered_quantity, received_quantity).value
                        ] += 1
            disputed = summary.get("disputed_amounts")
            return {
                "scope": "selected_run",
                "run": {
                    "id": str(run.id),
                    "title": run.title,
                    "mode": run.analysis_mode,
                    "completed_at": run.completed_at.astimezone(UTC).isoformat(),
                    "archived": run.archived_at is not None,
                },
                "availability": {
                    "has_purchase_orders": purchase_source is not None,
                    "has_receipts": receipt_source is not None,
                    "has_invoices": sources.get(SourceType.INVOICES) is not None,
                },
                "documents": documents,
                "lines": lines,
                "result_state": {
                    "matched_lines": summary.get("matched_lines"),
                    "review_required_lines": summary.get("review_required_lines"),
                },
                "issues": {"by_code": issue_counts, "by_category": category_counts},
                "fulfillment": fulfillment,
                "money": {
                    "ordered_value_by_currency": ordered,
                    "invoiced_value_by_currency": invoiced,
                    "authoritative_disputed_amounts_by_currency": dict(disputed)
                    if disputed is not None
                    else None,
                },
            }

    @staticmethod
    def _supplier_timing(
        session,
        organization: UUID,
        purchase_source: UUID,
        receipt_source: UUID,
        supplier_codes: list[str],
    ) -> dict[str, dict[str, object]]:
        rows = session.execute(
            select(
                db.PurchaseOrder.source_supplier_code,
                db.PurchaseOrderLine.id,
                db.PurchaseOrder.order_date,
                db.PurchaseOrderLine.ordered_quantity,
                db.GoodsReceiptLine.receipt_date,
                func.sum(db.GoodsReceiptLine.received_quantity),
            )
            .join(
                db.PurchaseOrderLine,
                (db.PurchaseOrderLine.organization_id == db.PurchaseOrder.organization_id)
                & (db.PurchaseOrderLine.purchase_order_id == db.PurchaseOrder.id),
            )
            .join(
                db.GoodsReceiptLine,
                (db.GoodsReceiptLine.organization_id == db.PurchaseOrderLine.organization_id)
                & (db.GoodsReceiptLine.resolved_purchase_order_line_id == db.PurchaseOrderLine.id),
            )
            .join(
                db.GoodsReceipt,
                (db.GoodsReceipt.organization_id == db.GoodsReceiptLine.organization_id)
                & (db.GoodsReceipt.id == db.GoodsReceiptLine.goods_receipt_id),
            )
            .where(
                db.PurchaseOrder.organization_id == organization,
                db.PurchaseOrder.source_file_id == purchase_source,
                db.GoodsReceipt.source_file_id == receipt_source,
                db.PurchaseOrder.source_supplier_code.in_(supplier_codes),
            )
            .group_by(
                db.PurchaseOrder.source_supplier_code,
                db.PurchaseOrderLine.id,
                db.PurchaseOrder.order_date,
                db.PurchaseOrderLine.ordered_quantity,
                db.GoodsReceiptLine.receipt_date,
            )
            .order_by(
                db.PurchaseOrder.source_supplier_code,
                db.PurchaseOrderLine.id,
                db.GoodsReceiptLine.receipt_date,
            )
        ).all()
        by_line: dict[tuple[str, UUID], dict[str, object]] = {}
        for code, line_id, order_date, ordered_quantity, receipt_date, quantity in rows:
            line = by_line.setdefault(
                (code, line_id),
                {"order_date": order_date, "ordered": ordered_quantity, "receipts": []},
            )
            line["receipts"].append((receipt_date, quantity))
        observed: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"first": [], "full": []})
        for (code, _), line in by_line.items():
            receipts = line["receipts"]
            first_date = receipts[0][0]
            observed[code]["first"].append((first_date - line["order_date"]).days)
            cumulative = Decimal(0)
            for receipt_date, quantity in receipts:
                cumulative += quantity
                if cumulative >= line["ordered"]:
                    observed[code]["full"].append((receipt_date - line["order_date"]).days)
                    break
        return {
            code: {
                "median_observed_days_to_first_receipt": median(values["first"]),
                "first_receipt_eligible_line_count": len(values["first"]),
                "median_observed_days_to_full_receipt": median(values["full"]),
                "full_receipt_eligible_line_count": len(values["full"]),
                "basis": "observed_in_selected_run_source_set",
            }
            for code, values in observed.items()
        }

    def suppliers(
        self,
        raw: str | None,
        run_id: UUID,
        *,
        limit: int = INTELLIGENCE_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, object]:
        if not 1 <= limit <= INTELLIGENCE_PAGE_MAX:
            raise AuthError(422, "invalid_limit", "Supplier page size is out of range.")
        after = decode_cursor(cursor, 1)[0] if cursor else None
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INTELLIGENCE) as (
            principal,
            session,
        ):
            organization = principal.active_organization_id
            run, snapshot, sources = self._selected_run(session, organization, run_id)
            identity_queries = []
            purchase_source = sources.get(SourceType.PURCHASE_ORDERS)
            invoice_source = sources.get(SourceType.INVOICES)
            if purchase_source:
                identity_queries.append(
                    select(
                        db.PurchaseOrder.source_supplier_code.label("supplier_code"),
                        db.PurchaseOrder.resolved_supplier_id.label("supplier_id"),
                    ).where(
                        db.PurchaseOrder.organization_id == organization,
                        db.PurchaseOrder.source_file_id == purchase_source,
                    )
                )
            if invoice_source:
                identity_queries.append(
                    select(
                        db.Invoice.source_supplier_code.label("supplier_code"),
                        db.Invoice.resolved_supplier_id.label("supplier_id"),
                    ).where(
                        db.Invoice.organization_id == organization,
                        db.Invoice.source_file_id == invoice_source,
                    )
                )
            if not identity_queries:
                return {
                    "scope": "selected_run",
                    "run_id": str(run.id),
                    "items": [],
                    "next_cursor": None,
                }
            identities = union_all(*identity_queries).subquery()
            code_query = select(identities.c.supplier_code).distinct()
            if after:
                code_query = code_query.where(identities.c.supplier_code > after)
            codes = list(
                session.scalars(code_query.order_by(identities.c.supplier_code).limit(limit + 1))
            )
            more = len(codes) > limit
            visible_codes = codes[:limit]
            if not visible_codes:
                return {
                    "scope": "selected_run",
                    "run_id": str(run.id),
                    "items": [],
                    "next_cursor": None,
                }
            identity_rows = session.execute(
                select(identities.c.supplier_code, identities.c.supplier_id)
                .distinct()
                .where(identities.c.supplier_code.in_(visible_codes))
            ).all()
            resolved_by_code = {
                code: supplier_id for code, supplier_id in identity_rows if supplier_id is not None
            }
            supplier_ids = set(resolved_by_code.values())
            labels = {
                supplier.id: supplier
                for supplier in session.scalars(
                    select(db.Supplier).where(
                        db.Supplier.organization_id == organization,
                        db.Supplier.id.in_(supplier_ids),
                    )
                )
            }
            items = {
                code: {
                    "identity": {
                        "supplier_code": code,
                        "resolved_supplier_id": str(resolved_by_code[code])
                        if code in resolved_by_code
                        else None,
                        "supplier_name": labels[resolved_by_code[code]].name
                        if code in resolved_by_code and resolved_by_code[code] in labels
                        else None,
                        "supplier_status": labels[resolved_by_code[code]].status
                        if code in resolved_by_code and resolved_by_code[code] in labels
                        else None,
                        "resolved": code in resolved_by_code,
                    },
                    "purchase_orders": {
                        "document_count": None if purchase_source is None else 0,
                        "line_count": None if purchase_source is None else 0,
                        "ordered_value_by_currency": None if purchase_source is None else {},
                    },
                    "invoices": {
                        "document_count": None if invoice_source is None else 0,
                        "line_count": None if invoice_source is None else 0,
                        "invoiced_value_by_currency": None if invoice_source is None else {},
                        "review_line_count": None if invoice_source is None else 0,
                    },
                    "issues": {"by_code": {}, "by_category": {}},
                    "receiving": None,
                    "receipt_timing": None,
                }
                for code in visible_codes
            }
            if purchase_source:
                rows = session.execute(
                    select(
                        db.PurchaseOrder.source_supplier_code,
                        db.PurchaseOrder.currency,
                        func.count(func.distinct(db.PurchaseOrder.id)),
                        func.count(db.PurchaseOrderLine.id),
                        func.sum(
                            db.PurchaseOrderLine.ordered_quantity * db.PurchaseOrderLine.unit_price
                        ),
                    )
                    .join(
                        db.PurchaseOrderLine,
                        (db.PurchaseOrderLine.organization_id == db.PurchaseOrder.organization_id)
                        & (db.PurchaseOrderLine.purchase_order_id == db.PurchaseOrder.id),
                    )
                    .where(
                        db.PurchaseOrder.organization_id == organization,
                        db.PurchaseOrder.source_file_id == purchase_source,
                        db.PurchaseOrder.source_supplier_code.in_(visible_codes),
                    )
                    .group_by(db.PurchaseOrder.source_supplier_code, db.PurchaseOrder.currency)
                )
                for code, currency, documents, line_count, value in rows:
                    entry = items[code]["purchase_orders"]
                    entry["document_count"] += int(documents)
                    entry["line_count"] += int(line_count)
                    entry["ordered_value_by_currency"][currency] = decimal_string(value)
            if invoice_source:
                rows = session.execute(
                    select(
                        db.Invoice.source_supplier_code,
                        db.Invoice.currency,
                        func.count(func.distinct(db.Invoice.id)),
                        func.count(db.InvoiceLine.id),
                        func.sum(db.InvoiceLine.invoiced_quantity * db.InvoiceLine.unit_price),
                    )
                    .join(
                        db.InvoiceLine,
                        (db.InvoiceLine.organization_id == db.Invoice.organization_id)
                        & (db.InvoiceLine.invoice_id == db.Invoice.id),
                    )
                    .where(
                        db.Invoice.organization_id == organization,
                        db.Invoice.source_file_id == invoice_source,
                        db.Invoice.source_supplier_code.in_(visible_codes),
                    )
                    .group_by(db.Invoice.source_supplier_code, db.Invoice.currency)
                )
                for code, currency, documents, line_count, value in rows:
                    entry = items[code]["invoices"]
                    entry["document_count"] += int(documents)
                    entry["line_count"] += int(line_count)
                    entry["invoiced_value_by_currency"][currency] = decimal_string(value)
            for row in snapshot.report.get("results", []):
                code = row.get("supplier_id")
                if code not in items:
                    continue
                if row.get("status") == "REVIEW_REQUIRED":
                    items[code]["invoices"]["review_line_count"] += 1
                issue_codes = list(row.get("issues", []))
                if row.get("status") == FulfillmentStatus.OVER_RECEIVED:
                    issue_codes.append("OVER_RECEIVED")
                for issue in issue_codes:
                    by_code = items[code]["issues"]["by_code"]
                    by_code[issue] = by_code.get(issue, 0) + 1
                    category = ISSUE_CATEGORIES[db.IssueCode(issue)].value
                    by_category = items[code]["issues"]["by_category"]
                    by_category[category] = by_category.get(category, 0) + 1
            receipt_source = sources.get(SourceType.RECEIPTS)
            if purchase_source and receipt_source:
                for entry in items.values():
                    entry["receiving"] = {status.value: 0 for status in FulfillmentStatus}
                if run.analysis_mode == AnalysisMode.PO_RECEIPT:
                    for row in snapshot.report.get("results", []):
                        code = row.get("supplier_id")
                        status = snapshot_fulfillment(row, run.analysis_mode)
                        if code in items and status is not None:
                            items[code]["receiving"][status.value] += 1
                else:
                    for code, ordered_quantity, received_quantity in self._source_fulfillment_rows(
                        session,
                        organization,
                        purchase_source,
                        receipt_source,
                        visible_codes,
                    ):
                        status = fulfillment_status(ordered_quantity, received_quantity)
                        items[code]["receiving"][status.value] += 1
                timings = self._supplier_timing(
                    session,
                    organization,
                    purchase_source,
                    receipt_source,
                    visible_codes,
                )
                empty_timing = {
                    "median_observed_days_to_first_receipt": None,
                    "first_receipt_eligible_line_count": 0,
                    "median_observed_days_to_full_receipt": None,
                    "full_receipt_eligible_line_count": 0,
                    "basis": "observed_in_selected_run_source_set",
                }
                for code, entry in items.items():
                    entry["receipt_timing"] = timings.get(code, empty_timing)
            return {
                "scope": "selected_run",
                "run_id": str(run.id),
                "items": [items[code] for code in visible_codes],
                "next_cursor": encode_cursor([visible_codes[-1]]) if more else None,
            }

    def inventory(
        self,
        raw: str | None,
        *,
        window: IntelligenceWindow = IntelligenceWindow.MONTH,
        limit: int = INTELLIGENCE_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, object]:
        if not 1 <= limit <= INTELLIGENCE_PAGE_MAX:
            raise AuthError(
                422, "invalid_limit", "Inventory intelligence page size is out of range."
            )
        after = decode_cursor(cursor, 4) if cursor else None
        if after:
            try:
                UUID(after[2])
                UUID(after[3])
            except ValueError:
                raise AuthError(
                    400, "invalid_cursor", "The intelligence cursor is invalid."
                ) from None
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INTELLIGENCE) as (
            principal,
            session,
        ):
            organization = principal.active_organization_id
            now = self.sessions.clock().astimezone(UTC)
            period = Period.at(window, now)
            active_items = session.scalar(
                select(func.count())
                .select_from(db.Item)
                .where(
                    db.Item.organization_id == organization,
                    db.Item.status == db.RecordStatus.ACTIVE,
                )
            )
            active_locations = session.scalar(
                select(func.count())
                .select_from(db.InventoryLocation)
                .where(
                    db.InventoryLocation.organization_id == organization,
                    db.InventoryLocation.status == db.RecordStatus.ACTIVE,
                )
            )
            balances = (
                select(
                    db.StockMovement.item_id,
                    db.StockMovement.location_id,
                    func.sum(db.StockMovement.quantity_delta).label("quantity"),
                )
                .where(db.StockMovement.organization_id == organization)
                .group_by(db.StockMovement.item_id, db.StockMovement.location_id)
                .subquery()
            )
            positive_positions = session.scalar(
                select(func.count()).select_from(balances).where(balances.c.quantity > 0)
            )
            operation_counts = {kind.value: 0 for kind in db.InventoryOperationType}
            for operation_type, count in session.execute(
                select(db.InventoryOperation.operation_type, func.count())
                .where(
                    db.InventoryOperation.organization_id == organization,
                    db.InventoryOperation.occurred_at >= period.start,
                    db.InventoryOperation.occurred_at < period.end,
                )
                .group_by(db.InventoryOperation.operation_type)
            ):
                operation_counts[operation_type.value] = int(count)
            in_period = and_(
                db.InventoryOperation.occurred_at >= period.start,
                db.InventoryOperation.occurred_at < period.end,
            )
            query = (
                select(
                    db.Item.id.label("item_id"),
                    db.Item.item_code,
                    db.Item.description,
                    db.Item.base_uom,
                    db.Item.status.label("item_status"),
                    db.InventoryLocation.id.label("location_id"),
                    db.InventoryLocation.location_code,
                    db.InventoryLocation.name.label("location_name"),
                    db.InventoryLocation.status.label("location_status"),
                    func.sum(db.StockMovement.quantity_delta).label("current_on_hand"),
                    func.count(
                        func.distinct(case((in_period, db.InventoryOperation.id), else_=None))
                    ).label("operation_count"),
                    func.coalesce(
                        func.sum(case((in_period, db.StockMovement.quantity_delta), else_=0)), 0
                    ).label("net_quantity_delta"),
                    func.max(db.InventoryOperation.occurred_at).label("last_movement_at"),
                    func.max(db.InventoryOperation.occurred_at)
                    .filter(db.StockMovement.quantity_delta > 0)
                    .label("last_inbound_at"),
                    func.max(db.InventoryOperation.occurred_at)
                    .filter(db.StockMovement.quantity_delta < 0)
                    .label("last_outbound_at"),
                )
                .join(
                    db.Item,
                    (db.Item.organization_id == db.StockMovement.organization_id)
                    & (db.Item.id == db.StockMovement.item_id),
                )
                .join(
                    db.InventoryLocation,
                    (db.InventoryLocation.organization_id == db.StockMovement.organization_id)
                    & (db.InventoryLocation.id == db.StockMovement.location_id),
                )
                .join(
                    db.InventoryOperation,
                    (db.InventoryOperation.organization_id == db.StockMovement.organization_id)
                    & (db.InventoryOperation.id == db.StockMovement.operation_id),
                )
                .where(db.StockMovement.organization_id == organization)
                .group_by(
                    db.Item.id,
                    db.Item.item_code,
                    db.Item.description,
                    db.Item.base_uom,
                    db.Item.status,
                    db.InventoryLocation.id,
                    db.InventoryLocation.location_code,
                    db.InventoryLocation.name,
                    db.InventoryLocation.status,
                )
            )
            if after:
                item_code, location_code, item_id, location_id = after
                query = query.where(
                    or_(
                        db.Item.item_code > item_code,
                        and_(
                            db.Item.item_code == item_code,
                            db.InventoryLocation.location_code > location_code,
                        ),
                        and_(
                            db.Item.item_code == item_code,
                            db.InventoryLocation.location_code == location_code,
                            db.Item.id > UUID(item_id),
                        ),
                        and_(
                            db.Item.item_code == item_code,
                            db.InventoryLocation.location_code == location_code,
                            db.Item.id == UUID(item_id),
                            db.InventoryLocation.id > UUID(location_id),
                        ),
                    )
                )
            rows = (
                session.execute(
                    query.order_by(
                        db.Item.item_code,
                        db.InventoryLocation.location_code,
                        db.Item.id,
                        db.InventoryLocation.id,
                    ).limit(limit + 1)
                )
                .mappings()
                .all()
            )
            more = len(rows) > limit
            visible = rows[:limit]

            def timestamp(value):
                return value.astimezone(UTC).isoformat() if value else None

            items = [
                {
                    "item": {
                        "id": str(row["item_id"]),
                        "item_code": row["item_code"],
                        "description": row["description"],
                        "base_uom": row["base_uom"],
                        "status": row["item_status"],
                    },
                    "location": {
                        "id": str(row["location_id"]),
                        "location_code": row["location_code"],
                        "name": row["location_name"],
                        "status": row["location_status"],
                    },
                    "current_on_hand": decimal_string(row["current_on_hand"]),
                    "operation_count": int(row["operation_count"]),
                    "net_ledger_quantity_delta": decimal_string(row["net_quantity_delta"]),
                    "last_movement_at": timestamp(row["last_movement_at"]),
                    "last_inbound_at": timestamp(row["last_inbound_at"]),
                    "last_outbound_at": timestamp(row["last_outbound_at"]),
                }
                for row in visible
            ]
            next_cursor = None
            if more:
                last = visible[-1]
                next_cursor = encode_cursor(
                    [
                        last["item_code"],
                        last["location_code"],
                        str(last["item_id"]),
                        str(last["location_id"]),
                    ]
                )
            return {
                "scope": "current_organization_inventory_ledger",
                "server_now": now.isoformat(),
                "period": period.payload(),
                "summary": {
                    "active_inventory_item_count": int(active_items),
                    "active_inventory_location_count": int(active_locations),
                    "positive_item_location_position_count": int(positive_positions),
                    "operation_counts_by_type": operation_counts,
                    "reversal_operation_count": operation_counts[
                        db.InventoryOperationType.REVERSAL.value
                    ],
                },
                "items": items,
                "next_cursor": next_cursor,
            }
