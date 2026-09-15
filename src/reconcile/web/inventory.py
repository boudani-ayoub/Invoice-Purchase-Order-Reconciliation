"""Inventory API with exact quantities and server-owned stock movement signs."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reconcile.persistence.inventory_policy import (
    BASE_UOM_LIMIT,
    INVENTORY_CODE_LIMIT,
    INVENTORY_NAME_LIMIT,
    INVENTORY_NOTE_LIMIT,
    INVENTORY_PAGE_MAX,
    INVENTORY_PAGE_SIZE,
    INVENTORY_REFERENCE_LIMIT,
)
from reconcile.persistence.models import InventoryOperationType, RecordStatus
from reconcile.web.auth import require_csrf, runtime, session_cookie
from reconcile.web.paths import INVENTORY_PATH

router = APIRouter(prefix=INVENTORY_PATH, tags=["Inventory"])
PageLimit = Annotated[int, Query(ge=1, le=INVENTORY_PAGE_MAX)]
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class InventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _trimmed(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Enter a nonblank value.")
    return normalized


class ItemCreate(InventoryInput):
    item_code: str = Field(min_length=1, max_length=INVENTORY_CODE_LIMIT)
    description: str = Field(min_length=1, max_length=INVENTORY_NAME_LIMIT)
    base_uom: str | None = Field(default=None, max_length=BASE_UOM_LIMIT)

    @field_validator("item_code", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return _trimmed(value)

    @field_validator("base_uom")
    @classmethod
    def normalize_uom(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _trimmed(value).upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", normalized):
            raise ValueError("Use a short unit token such as EA, KG, L, M, or BOX.")
        return normalized


class ItemUpdate(InventoryInput):
    expected_version: int = Field(gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=INVENTORY_NAME_LIMIT)
    base_uom: str | None = Field(default=None, max_length=BASE_UOM_LIMIT)

    @field_validator("description")
    @classmethod
    def trim_description(cls, value: str | None) -> str | None:
        return _trimmed(value) if value is not None else None

    @field_validator("base_uom")
    @classmethod
    def normalize_uom(cls, value: str | None) -> str | None:
        return ItemCreate.normalize_uom(value)

    @model_validator(mode="after")
    def requires_change(self) -> Self:
        if not ({"description", "base_uom"} & self.model_fields_set):
            raise ValueError("Provide a description or base unit.")
        return self


class LocationCreate(InventoryInput):
    location_code: str = Field(min_length=1, max_length=INVENTORY_CODE_LIMIT)
    name: str = Field(min_length=1, max_length=INVENTORY_NAME_LIMIT)

    @field_validator("location_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _trimmed(value).upper()

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return _trimmed(value)


class LocationUpdate(InventoryInput):
    expected_version: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=INVENTORY_NAME_LIMIT)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return _trimmed(value)


class ExpectedVersion(InventoryInput):
    expected_version: int = Field(gt=0)


class PostingInput(InventoryInput):
    idempotency_key: UUID
    quantity: Decimal
    occurred_at: datetime | None = None
    external_reference: str | None = Field(default=None, max_length=INVENTORY_REFERENCE_LIMIT)
    note: str | None = Field(default=None, max_length=INVENTORY_NOTE_LIMIT)

    @field_validator("quantity", mode="before")
    @classmethod
    def exact_decimal_string(cls, value: object) -> Decimal:
        if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
            raise ValueError("Quantity must be a positive decimal string.")
        quantity = Decimal(value)
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return quantity

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Occurred time must include a timezone.")
        return value

    @field_validator("external_reference", "note")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class MovementCreate(PostingInput):
    type: InventoryOperationType
    item_id: UUID
    location_id: UUID


class TransferCreate(PostingInput):
    item_id: UUID
    source_location_id: UUID
    destination_location_id: UUID


class ReversalCreate(InventoryInput):
    idempotency_key: UUID
    note: str | None = Field(default=None, max_length=INVENTORY_NOTE_LIMIT)

    @field_validator("note")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


def service(request: Request):
    auth = runtime(request)
    return auth.inventory, session_cookie(request, auth)


@router.get("/items")
def items(
    request: Request,
    limit: PageLimit = INVENTORY_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
    search: str | None = Query(default=None, max_length=100),
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.list_items(raw, limit=limit, cursor=cursor, search=search)


@router.post("/items", status_code=201, dependencies=[Depends(require_csrf)])
def create_item(body: ItemCreate, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.create_item(
        raw, item_code=body.item_code, description=body.description, base_uom=body.base_uom
    )


@router.get("/items/{item_id}")
def item(item_id: UUID, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.get_item(raw, item_id)


@router.patch("/items/{item_id}", dependencies=[Depends(require_csrf)])
def update_item(item_id: UUID, body: ItemUpdate, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.update_item(
        raw,
        item_id,
        expected_version=body.expected_version,
        description=body.description,
        base_uom=body.base_uom,
        update_description="description" in body.model_fields_set,
        update_base_uom="base_uom" in body.model_fields_set,
    )


@router.post("/items/{item_id}/archive", dependencies=[Depends(require_csrf)])
def archive_item(item_id: UUID, body: ExpectedVersion, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.set_item_status(
        raw, item_id, expected_version=body.expected_version, status=RecordStatus.ARCHIVED
    )


@router.post("/items/{item_id}/restore", dependencies=[Depends(require_csrf)])
def restore_item(item_id: UUID, body: ExpectedVersion, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.set_item_status(
        raw, item_id, expected_version=body.expected_version, status=RecordStatus.ACTIVE
    )


@router.get("/locations")
def locations(
    request: Request,
    limit: PageLimit = INVENTORY_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.list_locations(raw, limit=limit, cursor=cursor)


@router.post("/locations", status_code=201, dependencies=[Depends(require_csrf)])
def create_location(body: LocationCreate, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.create_location(raw, location_code=body.location_code, name=body.name)


@router.get("/locations/{location_id}")
def location(location_id: UUID, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.get_location(raw, location_id)


@router.patch("/locations/{location_id}", dependencies=[Depends(require_csrf)])
def update_location(location_id: UUID, body: LocationUpdate, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.update_location(
        raw, location_id, expected_version=body.expected_version, name=body.name
    )


@router.post("/locations/{location_id}/archive", dependencies=[Depends(require_csrf)])
def archive_location(
    location_id: UUID, body: ExpectedVersion, request: Request
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.set_location_status(
        raw, location_id, expected_version=body.expected_version, status=RecordStatus.ARCHIVED
    )


@router.post("/locations/{location_id}/restore", dependencies=[Depends(require_csrf)])
def restore_location(
    location_id: UUID, body: ExpectedVersion, request: Request
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.set_location_status(
        raw, location_id, expected_version=body.expected_version, status=RecordStatus.ACTIVE
    )


@router.get("/balances")
def balances(
    request: Request,
    limit: PageLimit = INVENTORY_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
    item_id: UUID | None = None,
    location_id: UUID | None = None,
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.balances(
        raw, limit=limit, cursor=cursor, item_id=item_id, location_id=location_id
    )


@router.get("/operations")
def operations(
    request: Request,
    limit: PageLimit = INVENTORY_PAGE_SIZE,
    cursor: str | None = Query(default=None, max_length=512),
    type: InventoryOperationType | None = None,
    item_id: UUID | None = None,
    location_id: UUID | None = None,
) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.list_operations(
        raw,
        limit=limit,
        cursor=cursor,
        operation_type=type,
        item_id=item_id,
        location_id=location_id,
    )


@router.get("/operations/{operation_id}")
def operation(operation_id: UUID, request: Request) -> dict[str, object]:
    inventory, raw = service(request)
    return inventory.get_operation(raw, operation_id)


def _posting_response(result) -> JSONResponse:
    return JSONResponse(status_code=201 if result.created else 200, content=result.payload)


@router.post("/movements", dependencies=[Depends(require_csrf)])
def create_movement(body: MovementCreate, request: Request) -> JSONResponse:
    inventory, raw = service(request)
    return _posting_response(
        inventory.post_movement(
            raw,
            operation_type=body.type,
            item_id=body.item_id,
            location_id=body.location_id,
            quantity=body.quantity,
            occurred_at=body.occurred_at,
            external_reference=body.external_reference,
            note=body.note,
            idempotency_key=body.idempotency_key,
            request_id=request.state.request_id,
        )
    )


@router.post("/transfers", dependencies=[Depends(require_csrf)])
def create_transfer(body: TransferCreate, request: Request) -> JSONResponse:
    inventory, raw = service(request)
    return _posting_response(
        inventory.transfer(
            raw,
            item_id=body.item_id,
            source_location_id=body.source_location_id,
            destination_location_id=body.destination_location_id,
            quantity=body.quantity,
            occurred_at=body.occurred_at,
            external_reference=body.external_reference,
            note=body.note,
            idempotency_key=body.idempotency_key,
            request_id=request.state.request_id,
        )
    )


@router.post("/operations/{operation_id}/reverse", dependencies=[Depends(require_csrf)])
def reverse_operation(operation_id: UUID, body: ReversalCreate, request: Request) -> JSONResponse:
    inventory, raw = service(request)
    return _posting_response(
        inventory.reverse(
            raw,
            operation_id,
            idempotency_key=body.idempotency_key,
            note=body.note,
            request_id=request.state.request_id,
        )
    )
