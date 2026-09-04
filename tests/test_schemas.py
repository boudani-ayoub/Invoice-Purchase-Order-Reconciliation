from reconcile.schemas import (
    GOODS_RECEIPT_SCHEMA,
    INVOICE_SCHEMA,
    PURCHASE_ORDER_SCHEMA,
    ColumnType,
    DuplicatePolicy,
)


def test_purchase_order_key_identifies_a_line() -> None:
    assert PURCHASE_ORDER_SCHEMA.key_columns == ("po_number", "line_number")
    assert PURCHASE_ORDER_SCHEMA.duplicate_policy is DuplicatePolicy.REJECT


def test_receipt_key_identifies_a_receipt_line() -> None:
    assert GOODS_RECEIPT_SCHEMA.key_columns == ("receipt_id", "line_number")
    assert GOODS_RECEIPT_SCHEMA.duplicate_policy is DuplicatePolicy.REJECT


def test_invoice_key_includes_supplier_and_line() -> None:
    assert INVOICE_SCHEMA.key_columns == ("supplier_id", "invoice_number", "line_number")
    assert INVOICE_SCHEMA.duplicate_policy is DuplicatePolicy.REVIEW


def test_prices_are_non_negative_while_quantities_are_positive() -> None:
    column_types = {column.name: column.data_type for column in PURCHASE_ORDER_SCHEMA.columns}

    assert column_types["ordered_quantity"] is ColumnType.POSITIVE_DECIMAL
    assert column_types["unit_price"] is ColumnType.NON_NEGATIVE_DECIMAL


def test_identifier_and_description_blank_policies_are_explicit() -> None:
    column_types = {column.name: column.data_type for column in PURCHASE_ORDER_SCHEMA.columns}

    assert column_types["po_number"] is ColumnType.NON_EMPTY_TEXT
    assert column_types["supplier_id"] is ColumnType.NON_EMPTY_TEXT
    assert column_types["item_code"] is ColumnType.NON_EMPTY_TEXT
    assert column_types["description"] is ColumnType.TEXT


def test_all_schema_headers_are_unique() -> None:
    for schema in (PURCHASE_ORDER_SCHEMA, GOODS_RECEIPT_SCHEMA, INVOICE_SCHEMA):
        assert len(schema.headers) == len(set(schema.headers))
