"""Tenant-scoped inventory master data and append-only stock operations."""

from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence import models as db


@dataclass(frozen=True)
class PostedOperation:
    payload: dict[str, object]
    created: bool


def _quantity(value: Decimal) -> str:
    return format(value, "f")


def _cursor(values: list[str]) -> str:
    raw = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(raw: str | None, expected: int) -> list[str] | None:
    if raw is None:
        return None
    try:
        padding = "=" * (-len(raw) % 4)
        values = json.loads(base64.urlsafe_b64decode(raw + padding))
        if not isinstance(values, list) or len(values) != expected:
            raise ValueError
        return [str(value) for value in values]
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise AuthError(422, "invalid_cursor", "Refresh the list and try again.") from None


def _cursor_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise AuthError(422, "invalid_cursor", "Refresh the list and try again.") from None


def _cursor_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise AuthError(422, "invalid_cursor", "Refresh the list and try again.") from None
    if parsed.tzinfo is None:
        raise AuthError(422, "invalid_cursor", "Refresh the list and try again.")
    return parsed


def _fingerprint(intent: dict[str, object]) -> str:
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode()).hexdigest()


def _item(record: db.Item) -> dict[str, object]:
    return {
        "id": str(record.id),
        "item_code": record.item_code,
        "description": record.description,
        "base_uom": record.base_uom,
        "status": record.status,
        "version": record.version,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _location(record: db.InventoryLocation) -> dict[str, object]:
    return {
        "id": str(record.id),
        "location_code": record.location_code,
        "name": record.name,
        "status": record.status,
        "version": record.version,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


class Inventory:
    def __init__(self, sessions: Sessions, clock) -> None:
        self.sessions = sessions
        self.clock = clock

    def list_items(
        self, raw: str | None, *, limit: int, cursor: str | None, search: str | None
    ) -> dict[str, object]:
        after = _decode_cursor(cursor, 2)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            query = select(db.Item)
            if search:
                pattern = f"%{search.strip()}%"
                query = query.where(
                    or_(db.Item.item_code.ilike(pattern), db.Item.description.ilike(pattern))
                )
            if after:
                item_id = _cursor_uuid(after[1])
                query = query.where(
                    or_(
                        db.Item.item_code > after[0],
                        and_(db.Item.item_code == after[0], db.Item.id > item_id),
                    )
                )
            rows = list(
                session.scalars(query.order_by(db.Item.item_code, db.Item.id).limit(limit + 1))
            )
            return self._page(rows, limit, _item, lambda row: [row.item_code, str(row.id)])

    def get_item(self, raw: str | None, item_id: UUID) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            record = session.get(db.Item, item_id)
            if record is None:
                raise self._not_found("item")
            return _item(record)

    def create_item(
        self, raw: str | None, *, item_code: str, description: str, base_uom: str | None
    ) -> dict[str, object]:
        try:
            with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
                principal,
                session,
            ):
                record = db.Item(
                    organization_id=principal.active_organization_id,
                    item_code=item_code,
                    description=description,
                    base_uom=base_uom,
                )
                session.add(record)
                session.flush()
                return _item(record)
        except IntegrityError:
            raise AuthError(
                409, "duplicate_item", "An item with this code already exists."
            ) from None

    def update_item(
        self,
        raw: str | None,
        item_id: UUID,
        *,
        expected_version: int,
        description: str | None,
        base_uom: str | None,
        update_description: bool,
        update_base_uom: bool,
    ) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
            principal,
            session,
        ):
            record = self._locked_item(session, principal.active_organization_id, item_id)
            self._version(record.version, expected_version)
            if (
                update_base_uom
                and record.base_uom != base_uom
                and self._item_has_movements(session, item_id)
            ):
                raise AuthError(
                    409,
                    "base_uom_locked",
                    "The base unit cannot change after the first stock movement.",
                )
            if update_description:
                record.description = description
            if update_base_uom:
                record.base_uom = base_uom
            record.version += 1
            session.flush()
            return _item(record)

    def set_item_status(
        self,
        raw: str | None,
        item_id: UUID,
        *,
        expected_version: int,
        status: db.RecordStatus,
    ) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
            principal,
            session,
        ):
            record = self._locked_item(session, principal.active_organization_id, item_id)
            self._version(record.version, expected_version)
            if status == db.RecordStatus.ARCHIVED and self._item_balance(session, item_id) != 0:
                raise AuthError(
                    409, "stock_remaining", "An item with on-hand stock cannot be archived."
                )
            record.status = status
            record.version += 1
            session.flush()
            return _item(record)

    def list_locations(
        self, raw: str | None, *, limit: int, cursor: str | None
    ) -> dict[str, object]:
        after = _decode_cursor(cursor, 2)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            query = select(db.InventoryLocation)
            if after:
                location_id = _cursor_uuid(after[1])
                query = query.where(
                    or_(
                        db.InventoryLocation.location_code > after[0],
                        and_(
                            db.InventoryLocation.location_code == after[0],
                            db.InventoryLocation.id > location_id,
                        ),
                    )
                )
            rows = list(
                session.scalars(
                    query.order_by(
                        db.InventoryLocation.location_code, db.InventoryLocation.id
                    ).limit(limit + 1)
                )
            )
            return self._page(rows, limit, _location, lambda row: [row.location_code, str(row.id)])

    def get_location(self, raw: str | None, location_id: UUID) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            record = session.get(db.InventoryLocation, location_id)
            if record is None:
                raise self._not_found("location")
            return _location(record)

    def create_location(
        self, raw: str | None, *, location_code: str, name: str
    ) -> dict[str, object]:
        try:
            with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
                principal,
                session,
            ):
                record = db.InventoryLocation(
                    organization_id=principal.active_organization_id,
                    location_code=location_code,
                    name=name,
                )
                session.add(record)
                session.flush()
                return _location(record)
        except IntegrityError:
            raise AuthError(
                409, "duplicate_location", "A location with this code already exists."
            ) from None

    def update_location(
        self,
        raw: str | None,
        location_id: UUID,
        *,
        expected_version: int,
        name: str,
    ) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
            principal,
            session,
        ):
            record = self._locked_locations(
                session, principal.active_organization_id, [location_id]
            )[0]
            self._version(record.version, expected_version)
            record.name = name
            record.version += 1
            session.flush()
            return _location(record)

    def set_location_status(
        self,
        raw: str | None,
        location_id: UUID,
        *,
        expected_version: int,
        status: db.RecordStatus,
    ) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.MANAGE_INVENTORY_MASTER) as (
            principal,
            session,
        ):
            record = self._locked_locations(
                session, principal.active_organization_id, [location_id]
            )[0]
            self._version(record.version, expected_version)
            if (
                status == db.RecordStatus.ARCHIVED
                and self._location_balance(session, location_id) != 0
            ):
                raise AuthError(
                    409,
                    "stock_remaining",
                    "A location with on-hand stock cannot be archived.",
                )
            record.status = status
            record.version += 1
            session.flush()
            return _location(record)

    def balances(
        self,
        raw: str | None,
        *,
        limit: int,
        cursor: str | None,
        item_id: UUID | None,
        location_id: UUID | None,
    ) -> dict[str, object]:
        after = _decode_cursor(cursor, 4)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            quantity = func.sum(db.StockMovement.quantity_delta).label("quantity")
            query = (
                select(db.Item, db.InventoryLocation, quantity)
                .join(db.StockMovement, db.StockMovement.item_id == db.Item.id)
                .join(
                    db.InventoryLocation,
                    db.InventoryLocation.id == db.StockMovement.location_id,
                )
                .group_by(db.Item.id, db.InventoryLocation.id)
            )
            if item_id:
                query = query.where(db.Item.id == item_id)
            if location_id:
                query = query.where(db.InventoryLocation.id == location_id)
            if after:
                item_cursor = _cursor_uuid(after[2])
                location_cursor = _cursor_uuid(after[3])
                query = query.where(
                    or_(
                        db.Item.item_code > after[0],
                        and_(
                            db.Item.item_code == after[0],
                            db.InventoryLocation.location_code > after[1],
                        ),
                        and_(
                            db.Item.item_code == after[0],
                            db.InventoryLocation.location_code == after[1],
                            db.Item.id > item_cursor,
                        ),
                        and_(
                            db.Item.item_code == after[0],
                            db.InventoryLocation.location_code == after[1],
                            db.Item.id == item_cursor,
                            db.InventoryLocation.id > location_cursor,
                        ),
                    )
                )
            rows = session.execute(
                query.order_by(
                    db.Item.item_code,
                    db.InventoryLocation.location_code,
                    db.Item.id,
                    db.InventoryLocation.id,
                ).limit(limit + 1)
            ).all()
            more = len(rows) > limit
            visible = rows[:limit]
            return {
                "items": [
                    {
                        "item": _item(item),
                        "location": _location(location),
                        "quantity": _quantity(quantity_value),
                    }
                    for item, location, quantity_value in visible
                ],
                "next_cursor": _cursor(
                    [
                        visible[-1][0].item_code,
                        visible[-1][1].location_code,
                        str(visible[-1][0].id),
                        str(visible[-1][1].id),
                    ]
                )
                if more
                else None,
            }

    def list_operations(
        self,
        raw: str | None,
        *,
        limit: int,
        cursor: str | None,
        operation_type: db.InventoryOperationType | None,
        item_id: UUID | None,
        location_id: UUID | None,
    ) -> dict[str, object]:
        after = _decode_cursor(cursor, 2)
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            query = select(db.InventoryOperation)
            if operation_type:
                query = query.where(db.InventoryOperation.operation_type == operation_type)
            movement_filter = [
                db.StockMovement.organization_id == db.InventoryOperation.organization_id,
                db.StockMovement.operation_id == db.InventoryOperation.id,
            ]
            if item_id:
                movement_filter.append(db.StockMovement.item_id == item_id)
            if location_id:
                movement_filter.append(db.StockMovement.location_id == location_id)
            if item_id or location_id:
                query = query.where(exists(select(1).where(*movement_filter)))
            if after:
                created_at = _cursor_datetime(after[0])
                operation_id = _cursor_uuid(after[1])
                query = query.where(
                    or_(
                        db.InventoryOperation.created_at < created_at,
                        and_(
                            db.InventoryOperation.created_at == created_at,
                            db.InventoryOperation.id < operation_id,
                        ),
                    )
                )
            rows = list(
                session.scalars(
                    query.order_by(
                        db.InventoryOperation.created_at.desc(), db.InventoryOperation.id.desc()
                    ).limit(limit + 1)
                )
            )
            more = len(rows) > limit
            visible = rows[:limit]
            payloads = self._operations(session, visible)
            return {
                "items": payloads,
                "next_cursor": _cursor([visible[-1].created_at.isoformat(), str(visible[-1].id)])
                if more
                else None,
            }

    def get_operation(self, raw: str | None, operation_id: UUID) -> dict[str, object]:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_INVENTORY) as (_, session):
            operation = session.get(db.InventoryOperation, operation_id)
            if operation is None:
                raise self._not_found("operation")
            return self._operations(session, [operation])[0]

    def post_movement(
        self,
        raw: str | None,
        *,
        operation_type: db.InventoryOperationType,
        item_id: UUID,
        location_id: UUID,
        quantity: Decimal,
        occurred_at: datetime | None,
        external_reference: str | None,
        note: str | None,
        idempotency_key: UUID,
        request_id: UUID,
    ) -> PostedOperation:
        allowed = {
            db.InventoryOperationType.OPENING_BALANCE,
            db.InventoryOperationType.STOCK_RECEIPT,
            db.InventoryOperationType.STOCK_ISSUE,
            db.InventoryOperationType.ADJUSTMENT_IN,
            db.InventoryOperationType.ADJUSTMENT_OUT,
        }
        if operation_type not in allowed:
            raise AuthError(422, "invalid_operation", "Use the dedicated transfer or reversal API.")
        intent = {
            "type": operation_type.value,
            "item_id": str(item_id),
            "location_id": str(location_id),
            "quantity": _quantity(quantity),
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "external_reference": external_reference,
            "note": note,
        }
        return self._post(
            raw,
            idempotency_key=idempotency_key,
            request_id=request_id,
            fingerprint=_fingerprint(intent),
            occurred_at=occurred_at,
            operation_type=operation_type,
            item_id=item_id,
            location_ids=[location_id],
            quantity=quantity,
            external_reference=external_reference,
            note=note,
        )

    def transfer(
        self,
        raw: str | None,
        *,
        item_id: UUID,
        source_location_id: UUID,
        destination_location_id: UUID,
        quantity: Decimal,
        occurred_at: datetime | None,
        external_reference: str | None,
        note: str | None,
        idempotency_key: UUID,
        request_id: UUID,
    ) -> PostedOperation:
        if source_location_id == destination_location_id:
            raise AuthError(422, "same_location", "Choose two different locations.")
        intent = {
            "type": db.InventoryOperationType.TRANSFER.value,
            "item_id": str(item_id),
            "source_location_id": str(source_location_id),
            "destination_location_id": str(destination_location_id),
            "quantity": _quantity(quantity),
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "external_reference": external_reference,
            "note": note,
        }
        return self._post(
            raw,
            idempotency_key=idempotency_key,
            request_id=request_id,
            fingerprint=_fingerprint(intent),
            occurred_at=occurred_at,
            operation_type=db.InventoryOperationType.TRANSFER,
            item_id=item_id,
            location_ids=[source_location_id, destination_location_id],
            quantity=quantity,
            external_reference=external_reference,
            note=note,
            source_location_id=source_location_id,
        )

    def reverse(
        self,
        raw: str | None,
        operation_id: UUID,
        *,
        idempotency_key: UUID,
        note: str | None,
        request_id: UUID,
    ) -> PostedOperation:
        fingerprint = _fingerprint(
            {"type": "REVERSAL", "operation_id": str(operation_id), "note": note}
        )
        with self.sessions.authorized_transaction(raw, Permission.POST_INVENTORY) as (
            principal,
            session,
        ):
            organization_id = principal.active_organization_id
            replay = self._idempotency(
                session, organization_id, principal.user_id, idempotency_key, fingerprint
            )
            if replay:
                return PostedOperation(self._operations(session, [replay])[0], False)
            original = session.scalar(
                select(db.InventoryOperation).where(db.InventoryOperation.id == operation_id)
            )
            if original is None:
                raise self._not_found("operation")
            if original.operation_type == db.InventoryOperationType.REVERSAL:
                raise AuthError(409, "reversal_not_reversible", "A reversal cannot be reversed.")
            movements = list(
                session.scalars(
                    select(db.StockMovement)
                    .where(db.StockMovement.operation_id == original.id)
                    .order_by(db.StockMovement.location_id, db.StockMovement.id)
                )
            )
            item_ids = sorted({movement.item_id for movement in movements})
            items = list(
                session.scalars(
                    select(db.Item)
                    .where(db.Item.id.in_(item_ids))
                    .order_by(db.Item.id)
                    .with_for_update()
                )
            )
            if len(items) != len(item_ids) or any(
                item.status != db.RecordStatus.ACTIVE for item in items
            ):
                raise AuthError(409, "inactive_item", "Restore the item before posting inventory.")
            location_ids = sorted({movement.location_id for movement in movements})
            locations = self._locked_locations(session, organization_id, location_ids)
            if any(location.status != db.RecordStatus.ACTIVE for location in locations):
                raise AuthError(
                    409, "inactive_location", "Restore the location before posting inventory."
                )
            if session.scalar(
                select(db.InventoryOperation.id).where(
                    db.InventoryOperation.reverses_operation_id == original.id
                )
            ):
                raise AuthError(
                    409, "already_reversed", "This operation has already been reversed."
                )
            for movement in movements:
                if (
                    self._balance(session, movement.item_id, movement.location_id)
                    - movement.quantity_delta
                    < 0
                ):
                    raise self._insufficient()
            now = self.clock()
            reversal = db.InventoryOperation(
                organization_id=organization_id,
                operation_type=db.InventoryOperationType.REVERSAL,
                actor_user_id=principal.user_id,
                occurred_at=now,
                created_at=now,
                updated_at=now,
                note=note,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                reverses_operation_id=original.id,
            )
            session.add(reversal)
            session.flush()
            session.add_all(
                [
                    db.StockMovement(
                        organization_id=organization_id,
                        operation_id=reversal.id,
                        item_id=movement.item_id,
                        location_id=movement.location_id,
                        quantity_delta=-movement.quantity_delta,
                    )
                    for movement in movements
                ]
            )
            session.flush()
            return PostedOperation(self._operations(session, [reversal])[0], True)

    def _post(
        self,
        raw: str | None,
        *,
        idempotency_key: UUID,
        request_id: UUID,
        fingerprint: str,
        occurred_at: datetime | None,
        operation_type: db.InventoryOperationType,
        item_id: UUID,
        location_ids: list[UUID],
        quantity: Decimal,
        external_reference: str | None,
        note: str | None,
        source_location_id: UUID | None = None,
    ) -> PostedOperation:
        if not quantity.is_finite() or quantity <= 0:
            raise AuthError(422, "invalid_quantity", "Enter a positive decimal quantity.")
        with self.sessions.authorized_transaction(raw, Permission.POST_INVENTORY) as (
            principal,
            session,
        ):
            organization_id = principal.active_organization_id
            replay = self._idempotency(
                session, organization_id, principal.user_id, idempotency_key, fingerprint
            )
            if replay:
                return PostedOperation(self._operations(session, [replay])[0], False)
            item = self._locked_item(session, organization_id, item_id)
            if item.status != db.RecordStatus.ACTIVE:
                raise AuthError(409, "inactive_item", "Restore the item before posting inventory.")
            if item.base_uom is None:
                raise AuthError(409, "base_uom_required", "Configure the item's base unit first.")
            locations = self._locked_locations(session, organization_id, location_ids)
            if any(location.status != db.RecordStatus.ACTIVE for location in locations):
                raise AuthError(
                    409, "inactive_location", "Restore the location before posting inventory."
                )
            now = self.clock()
            occurred = occurred_at or now
            if occurred.tzinfo is None:
                raise AuthError(422, "invalid_occurred_at", "Use a timezone-aware occurred time.")
            if occurred.astimezone(UTC) > now.astimezone(UTC):
                raise AuthError(
                    422, "future_occurred_at", "Stock operations cannot be future-dated."
                )
            if operation_type == db.InventoryOperationType.OPENING_BALANCE and session.scalar(
                select(
                    exists().where(
                        db.StockMovement.item_id == item_id,
                        db.StockMovement.location_id == location_ids[0],
                    )
                )
            ):
                raise AuthError(
                    409,
                    "opening_balance_exists",
                    "Opening balance is only allowed before inventory history exists.",
                )
            outbound = operation_type in {
                db.InventoryOperationType.STOCK_ISSUE,
                db.InventoryOperationType.ADJUSTMENT_OUT,
                db.InventoryOperationType.TRANSFER,
            }
            outbound_location = source_location_id or location_ids[0]
            if outbound and self._balance(session, item_id, outbound_location) < quantity:
                raise self._insufficient()
            operation = db.InventoryOperation(
                organization_id=organization_id,
                operation_type=operation_type,
                actor_user_id=principal.user_id,
                occurred_at=occurred,
                created_at=now,
                updated_at=now,
                external_reference=external_reference,
                note=note,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
            session.add(operation)
            session.flush()
            if operation_type == db.InventoryOperationType.TRANSFER:
                deltas = {
                    source_location_id: -quantity,
                    next(
                        location for location in location_ids if location != source_location_id
                    ): quantity,
                }
            else:
                sign = -1 if outbound else 1
                deltas = {location_ids[0]: quantity * sign}
            session.add_all(
                [
                    db.StockMovement(
                        organization_id=organization_id,
                        operation_id=operation.id,
                        item_id=item_id,
                        location_id=location_id,
                        quantity_delta=deltas[location_id],
                    )
                    for location_id in sorted(deltas)
                ]
            )
            session.flush()
            return PostedOperation(self._operations(session, [operation])[0], True)

    def _idempotency(
        self,
        session: Session,
        organization_id: UUID,
        actor_user_id: UUID,
        key: UUID,
        fingerprint: str,
    ) -> db.InventoryOperation | None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{organization_id}:{key}"},
        )
        existing = session.scalar(
            select(db.InventoryOperation).where(db.InventoryOperation.idempotency_key == key)
        )
        if existing and (
            existing.actor_user_id != actor_user_id or existing.request_fingerprint != fingerprint
        ):
            raise AuthError(
                409,
                "idempotency_conflict",
                "This idempotency key was already used for a different inventory request.",
            )
        return existing

    @staticmethod
    def _locked_item(session: Session, organization_id: UUID, item_id: UUID) -> db.Item:
        record = session.scalar(
            select(db.Item)
            .where(db.Item.organization_id == organization_id, db.Item.id == item_id)
            .with_for_update()
        )
        if record is None:
            raise Inventory._not_found("item")
        return record

    @staticmethod
    def _locked_locations(
        session: Session, organization_id: UUID, location_ids: list[UUID]
    ) -> list[db.InventoryLocation]:
        unique_ids = sorted(set(location_ids))
        records = list(
            session.scalars(
                select(db.InventoryLocation)
                .where(
                    db.InventoryLocation.organization_id == organization_id,
                    db.InventoryLocation.id.in_(unique_ids),
                )
                .order_by(db.InventoryLocation.id)
                .with_for_update()
            )
        )
        if len(records) != len(unique_ids):
            raise Inventory._not_found("location")
        return records

    @staticmethod
    def _balance(session: Session, item_id: UUID, location_id: UUID) -> Decimal:
        return session.scalar(
            select(func.coalesce(func.sum(db.StockMovement.quantity_delta), Decimal("0"))).where(
                db.StockMovement.item_id == item_id,
                db.StockMovement.location_id == location_id,
            )
        )

    @staticmethod
    def _item_balance(session: Session, item_id: UUID) -> Decimal:
        return session.scalar(
            select(func.coalesce(func.sum(db.StockMovement.quantity_delta), Decimal("0"))).where(
                db.StockMovement.item_id == item_id
            )
        )

    @staticmethod
    def _location_balance(session: Session, location_id: UUID) -> Decimal:
        return session.scalar(
            select(func.coalesce(func.sum(db.StockMovement.quantity_delta), Decimal("0"))).where(
                db.StockMovement.location_id == location_id
            )
        )

    @staticmethod
    def _item_has_movements(session: Session, item_id: UUID) -> bool:
        return bool(session.scalar(select(exists().where(db.StockMovement.item_id == item_id))))

    @staticmethod
    def _version(actual: int, expected: int) -> None:
        if actual != expected:
            raise AuthError(409, "version_conflict", "This record changed. Refresh and try again.")

    @staticmethod
    def _not_found(resource: str) -> AuthError:
        return AuthError(404, "not_found", f"The inventory {resource} was not found.")

    @staticmethod
    def _insufficient() -> AuthError:
        return AuthError(
            409,
            "insufficient_stock",
            "Insufficient on-hand quantity at this location. "
            "Refresh inventory before trying again.",
        )

    @staticmethod
    def _page(rows: list[Any], limit: int, render, key) -> dict[str, object]:
        more = len(rows) > limit
        visible = rows[:limit]
        return {
            "items": [render(row) for row in visible],
            "next_cursor": _cursor(key(visible[-1])) if more else None,
        }

    @staticmethod
    def _operations(
        session: Session, operations: list[db.InventoryOperation]
    ) -> list[dict[str, object]]:
        if not operations:
            return []
        operation_ids = [operation.id for operation in operations]
        rows = session.execute(
            select(db.StockMovement, db.Item, db.InventoryLocation)
            .join(db.Item, db.Item.id == db.StockMovement.item_id)
            .join(db.InventoryLocation, db.InventoryLocation.id == db.StockMovement.location_id)
            .where(db.StockMovement.operation_id.in_(operation_ids))
            .order_by(db.StockMovement.operation_id, db.StockMovement.location_id)
        ).all()
        movements: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for movement, item, location in rows:
            movements[movement.operation_id].append(
                {
                    "id": str(movement.id),
                    "item": {
                        "id": str(item.id),
                        "item_code": item.item_code,
                        "description": item.description,
                        "base_uom": item.base_uom,
                    },
                    "location": {
                        "id": str(location.id),
                        "location_code": location.location_code,
                        "name": location.name,
                    },
                    "quantity_delta": _quantity(movement.quantity_delta),
                }
            )
        return [
            {
                "id": str(operation.id),
                "type": operation.operation_type,
                "actor_user_id": str(operation.actor_user_id),
                "occurred_at": operation.occurred_at.isoformat(),
                "created_at": operation.created_at.isoformat(),
                "external_reference": operation.external_reference,
                "note": operation.note,
                "request_id": str(operation.request_id),
                "idempotency_key": str(operation.idempotency_key),
                "reverses_operation_id": str(operation.reverses_operation_id)
                if operation.reverses_operation_id
                else None,
                "movements": movements[operation.id],
            }
            for operation in operations
        ]
