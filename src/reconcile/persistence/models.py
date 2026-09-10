"""Relational source evidence; reconciliation decisions live in the domain package."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reconcile.analysis.models import AnalysisMode, SourceType
from reconcile.models import IssueCode
from reconcile.persistence.base import Base, Record, TenantRecord, tenant_constraints, tenant_fk
from reconcile.persistence.run_policy import NOTE_LIMIT, TITLE_LIMIT


class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MembershipRole(StrEnum):
    MEMBER = "MEMBER"
    AP_MANAGER = "AP_MANAGER"
    ORG_ADMIN = "ORG_ADMIN"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class FindingCategory(StrEnum):
    REFERENCE = "REFERENCE"
    DUPLICATE = "DUPLICATE"
    COMMERCIAL = "COMMERCIAL"
    QUANTITY = "QUANTITY"


def enum_type(enum: type[StrEnum]) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )


def positive(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} > 0 AND {column} < 'Infinity'::numeric", name=f"{column}_positive"
    )


def price(column: str = "unit_price") -> CheckConstraint:
    return CheckConstraint(
        f"{column} >= 0 AND {column} < 'Infinity'::numeric", name=f"{column}_nonnegative"
    )


def currency() -> CheckConstraint:
    return CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_code")


class Organization(Record, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_nonempty"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
    )
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus), server_default=RecordStatus.ACTIVE
    )


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email)) AND email ~ '^[^@[:space:]]+@[^@[:space:]]+$'",
            name="email_normalized",
        ),
    )
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus), server_default=RecordStatus.ACTIVE
    )


class OrganizationMembership(TenantRecord, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = tenant_constraints(UniqueConstraint("organization_id", "user_id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    role: Mapped[MembershipRole] = mapped_column(enum_type(MembershipRole))
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus), server_default=RecordStatus.ACTIVE
    )


class Supplier(TenantRecord, Base):
    __tablename__ = "suppliers"
    __table_args__ = tenant_constraints(
        UniqueConstraint("organization_id", "supplier_code"),
        CheckConstraint(
            "supplier_code <> '' AND supplier_code = btrim(supplier_code)", name="code_nonempty"
        ),
    )
    supplier_code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus), server_default=RecordStatus.ACTIVE
    )


class Item(TenantRecord, Base):
    __tablename__ = "items"
    __table_args__ = tenant_constraints(
        UniqueConstraint("organization_id", "item_code"),
        CheckConstraint("item_code <> '' AND item_code = btrim(item_code)", name="code_nonempty"),
    )
    item_code: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        enum_type(RecordStatus), server_default=RecordStatus.ACTIVE
    )


class SourceFile(TenantRecord, Base):
    __tablename__ = "source_files"
    __table_args__ = tenant_constraints(
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint(
            "original_filename <> '' AND original_filename !~ '[/\\\\]'", name="filename_not_path"
        ),
    )
    source_type: Mapped[SourceType] = mapped_column(enum_type(SourceType))
    original_filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)


class PurchaseOrder(TenantRecord, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = tenant_constraints(
        tenant_fk("source_file_id", "source_files"),
        tenant_fk("resolved_supplier_id", "suppliers"),
        UniqueConstraint("organization_id", "source_file_id", "po_number"),
        currency(),
        CheckConstraint(
            "po_number <> '' AND source_supplier_code <> ''", name="source_identity_nonempty"
        ),
    )
    source_file_id: Mapped[UUID]
    po_number: Mapped[str] = mapped_column(Text)
    source_supplier_code: Mapped[str] = mapped_column(Text)
    resolved_supplier_id: Mapped[UUID | None]
    order_date: Mapped[date]
    currency: Mapped[str] = mapped_column(Text)


class PurchaseOrderLine(TenantRecord, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = tenant_constraints(
        tenant_fk("purchase_order_id", "purchase_orders"),
        tenant_fk("resolved_item_id", "items"),
        UniqueConstraint("organization_id", "purchase_order_id", "line_number"),
        CheckConstraint("line_number > 0 AND source_row_number > 1", name="line_positive"),
        CheckConstraint("source_item_code <> ''", name="item_nonempty"),
        positive("ordered_quantity"),
        price(),
    )
    purchase_order_id: Mapped[UUID]
    line_number: Mapped[int] = mapped_column(BigInteger)
    source_row_number: Mapped[int] = mapped_column(BigInteger)
    source_item_code: Mapped[str] = mapped_column(Text)
    resolved_item_id: Mapped[UUID | None]
    description: Mapped[str] = mapped_column(Text)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric())
    unit_price: Mapped[Decimal] = mapped_column(Numeric())


class GoodsReceipt(TenantRecord, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = tenant_constraints(
        tenant_fk("source_file_id", "source_files"),
        UniqueConstraint("organization_id", "source_file_id", "receipt_number"),
        CheckConstraint("receipt_number <> ''", name="receipt_number_nonempty"),
    )
    source_file_id: Mapped[UUID]
    receipt_number: Mapped[str] = mapped_column(Text)


class SourceReference:
    source_po_number: Mapped[str] = mapped_column(Text)
    source_po_line_number: Mapped[int] = mapped_column(BigInteger)
    source_item_code: Mapped[str] = mapped_column(Text)
    resolved_purchase_order_line_id: Mapped[UUID | None]
    resolved_item_id: Mapped[UUID | None]


def reference_constraints():
    return (
        tenant_fk("resolved_purchase_order_line_id", "purchase_order_lines"),
        tenant_fk("resolved_item_id", "items"),
        CheckConstraint(
            "source_po_number <> '' AND source_item_code <> '' AND source_po_line_number > 0",
            name="source_reference_valid",
        ),
    )


class GoodsReceiptLine(SourceReference, TenantRecord, Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = tenant_constraints(
        tenant_fk("goods_receipt_id", "goods_receipts"),
        *reference_constraints(),
        UniqueConstraint("organization_id", "goods_receipt_id", "line_number"),
        CheckConstraint("line_number > 0 AND source_row_number > 1", name="line_positive"),
        positive("received_quantity"),
    )
    goods_receipt_id: Mapped[UUID]
    line_number: Mapped[int] = mapped_column(BigInteger)
    source_row_number: Mapped[int] = mapped_column(BigInteger)
    receipt_date: Mapped[date]
    received_quantity: Mapped[Decimal] = mapped_column(Numeric())


class Invoice(TenantRecord, Base):
    __tablename__ = "invoices"
    __table_args__ = tenant_constraints(
        tenant_fk("source_file_id", "source_files"),
        tenant_fk("resolved_supplier_id", "suppliers"),
        UniqueConstraint(
            "organization_id", "source_file_id", "source_supplier_code", "invoice_number"
        ),
        Index(
            "ix_invoices_logical_identity",
            "organization_id",
            "source_supplier_code",
            "invoice_number",
        ),
        currency(),
        CheckConstraint(
            "invoice_number <> '' AND source_supplier_code <> ''", name="source_identity_nonempty"
        ),
    )
    source_file_id: Mapped[UUID]
    invoice_number: Mapped[str] = mapped_column(Text)
    source_supplier_code: Mapped[str] = mapped_column(Text)
    resolved_supplier_id: Mapped[UUID | None]
    invoice_date: Mapped[date]
    currency: Mapped[str] = mapped_column(Text)


class InvoiceLine(SourceReference, TenantRecord, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = tenant_constraints(
        tenant_fk("invoice_id", "invoices"),
        *reference_constraints(),
        UniqueConstraint("organization_id", "invoice_id", "source_row_number"),
        Index("ix_invoice_lines_duplicate_key", "organization_id", "invoice_id", "line_number"),
        CheckConstraint("line_number > 0 AND source_row_number > 1", name="line_positive"),
        positive("invoiced_quantity"),
        price(),
    )
    invoice_id: Mapped[UUID]
    line_number: Mapped[int] = mapped_column(BigInteger)
    source_row_number: Mapped[int] = mapped_column(BigInteger)
    invoiced_quantity: Mapped[Decimal] = mapped_column(Numeric())
    unit_price: Mapped[Decimal] = mapped_column(Numeric())


class AnalysisRun(TenantRecord, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = tenant_constraints(
        ForeignKeyConstraint(
            ["organization_id", "created_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_analysis_runs_chronology", "organization_id", "created_at"),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="time_order",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR completed_at IS NOT NULL", name="completed_timestamp"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(f"title IS NULL OR length(title) <= {TITLE_LIMIT}", name="title_length"),
        CheckConstraint(f"note IS NULL OR length(note) <= {NOTE_LIMIT}", name="note_length"),
        CheckConstraint("archived_at IS NULL OR archived_at >= created_at", name="archive_time"),
        Index("ix_analysis_runs_history", "organization_id", "archived_at", "created_at", "id"),
        Index(
            "ix_analysis_runs_mode_history",
            "organization_id",
            "analysis_mode",
            "archived_at",
            "created_at",
            "id",
        ),
    )
    analysis_mode: Mapped[AnalysisMode] = mapped_column(enum_type(AnalysisMode))
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus), server_default=RunStatus.PENDING
    )
    created_by_user_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class AnalysisSource(TenantRecord, Base):
    __tablename__ = "analysis_sources"
    __table_args__ = tenant_constraints(
        tenant_fk("analysis_run_id", "analysis_runs"),
        tenant_fk("source_file_id", "source_files"),
        UniqueConstraint("organization_id", "analysis_run_id", "source_file_id"),
    )
    analysis_run_id: Mapped[UUID]
    source_file_id: Mapped[UUID]


class Finding(TenantRecord, Base):
    __tablename__ = "findings"
    __table_args__ = tenant_constraints(
        tenant_fk("analysis_run_id", "analysis_runs"),
        tenant_fk("invoice_line_id", "invoice_lines"),
        tenant_fk("purchase_order_line_id", "purchase_order_lines"),
        tenant_fk("goods_receipt_line_id", "goods_receipt_lines"),
        CheckConstraint(
            "num_nonnulls(invoice_line_id, purchase_order_line_id, goods_receipt_line_id) > 0",
            name="subject_required",
        ),
        Index("ix_findings_run_status", "organization_id", "analysis_run_id", "status"),
    )
    analysis_run_id: Mapped[UUID]
    code: Mapped[IssueCode] = mapped_column(enum_type(IssueCode))
    category: Mapped[FindingCategory] = mapped_column(enum_type(FindingCategory))
    status: Mapped[FindingStatus] = mapped_column(
        enum_type(FindingStatus), server_default=FindingStatus.OPEN
    )
    invoice_line_id: Mapped[UUID | None]
    purchase_order_line_id: Mapped[UUID | None]
    goods_receipt_line_id: Mapped[UUID | None]


class ResultSnapshot(TenantRecord, Base):
    __tablename__ = "result_snapshots"
    __table_args__ = tenant_constraints(
        tenant_fk("analysis_run_id", "analysis_runs"),
        UniqueConstraint("organization_id", "analysis_run_id"),
        CheckConstraint("schema_version > 0 AND engine_version <> ''", name="versions_present"),
        CheckConstraint(
            "jsonb_typeof(report) = 'object' AND report ? 'mode' "
            "AND report ? 'summary' AND report ? 'results'",
            name="report_envelope",
        ),
    )
    analysis_run_id: Mapped[UUID]
    schema_version: Mapped[int]
    engine_version: Mapped[str] = mapped_column(Text)
    report: Mapped[dict[str, object]] = mapped_column(JSONB)
