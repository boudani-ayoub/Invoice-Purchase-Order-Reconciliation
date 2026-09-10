import json
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from web_support import create_analysis_test_app as create_app

import reconcile.web.app as web_app
from reconcile import (
    load_goods_receipts,
    load_invoices,
    load_purchase_orders,
    reconcile,
    render_json_report,
)

SAMPLE_DIR = Path(__file__).parents[1] / "examples" / "sample_data"
SAMPLE_FILES = {
    "purchase_orders": SAMPLE_DIR / "purchase_orders.csv",
    "receipts": SAMPLE_DIR / "goods_receipts.csv",
    "invoices": SAMPLE_DIR / "invoices.csv",
}
INVALID_PURCHASE_ORDERS = (
    b"po_number,line_number,supplier_id,order_date,currency,item_code,description,"
    b"ordered_quantity,unit_price\n"
    b"PO-100,1,SUP-ONE,2026-02-01,MAD,ITEM-A,Item,-3,25.50\n"
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def request_directories(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    paths: list[Path] = []

    @contextmanager
    def tracked_directory() -> Iterator[str]:
        with TemporaryDirectory(prefix="reconcile-api-test-") as directory:
            paths.append(Path(directory))
            yield directory

    monkeypatch.setattr(web_app, "_request_directory", tracked_directory)
    return paths


def upload_files(
    *,
    purchase_orders: bytes | None = None,
    filenames: dict[str, str] | None = None,
) -> dict[str, tuple[str, bytes, str]]:
    names = filenames or {}
    return {
        field: (
            names.get(field, path.name),
            purchase_orders
            if field == "purchase_orders" and purchase_orders is not None
            else path.read_bytes(),
            "application/octet-stream",
        )
        for field, path in SAMPLE_FILES.items()
    }


def test_health_returns_package_version(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "version": version("invoice-purchase-order-reconciliation"),
    }


def test_builtin_api_documentation_is_available(client: TestClient) -> None:
    response = client.get("/docs")
    schema = client.get("/openapi.json").json()
    reconcile_operation = schema["paths"]["/api/v1/reconcile"]["post"]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Swagger UI" in response.text
    assert "multipart/form-data" in reconcile_operation["requestBody"]["content"]
    assert "application/json" in reconcile_operation["responses"]["200"]["content"]


def test_configured_frontend_origin_receives_narrow_cors_headers() -> None:
    origin = "http://localhost:3000"

    with TestClient(create_app(allowed_origins=[origin])) as test_client:
        response = test_client.options(
            "/api/v1/reconcile",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-methods"] == "GET, POST, PATCH"
    allowed_headers = response.headers["access-control-allow-headers"].lower().split(", ")
    assert "content-type" in allowed_headers
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unconfigured_frontend_origin_receives_no_cors_grant() -> None:
    with TestClient(create_app(allowed_origins=["http://localhost:3000"])) as test_client:
        response = test_client.options(
            "/api/v1/reconcile",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origins_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://127.0.0.1:3000"
    monkeypatch.setenv(web_app.ALLOWED_ORIGINS_ENV, f" {origin}/, {origin} ")

    with TestClient(create_app()) as test_client:
        response = test_client.options(
            "/api/v1/reconcile",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_single_explicit_origin_string_is_not_split_into_characters() -> None:
    origin = "http://localhost:3000"

    with TestClient(create_app(allowed_origins=origin)) as test_client:
        response = test_client.options(
            "/api/v1/reconcile",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not accept wildcard origins"):
        create_app(allowed_origins=["*"])


def test_sample_response_is_exactly_the_existing_json_report(
    client: TestClient,
    request_directories: list[Path],
) -> None:
    purchase_orders = load_purchase_orders(SAMPLE_FILES["purchase_orders"])
    receipts = load_goods_receipts(SAMPLE_FILES["receipts"])
    invoices = load_invoices(SAMPLE_FILES["invoices"])
    results, summary = reconcile(purchase_orders, receipts, invoices)
    rendered = render_json_report(results, summary)

    response = client.post("/api/v1/reconcile", files=upload_files())

    payload = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == rendered.encode("utf-8")
    assert payload == json.loads(rendered)
    assert payload["summary"] == {
        "invoices_processed": 15,
        "invoice_lines_processed": 17,
        "matched_lines": 6,
        "review_required_lines": 11,
        "issue_counts": {
            "UNKNOWN_PO": 1,
            "UNKNOWN_ITEM": 1,
            "DUPLICATE_INVOICE": 2,
            "SUPPLIER_MISMATCH": 1,
            "CURRENCY_MISMATCH": 1,
            "MISSING_RECEIPT": 1,
            "QUANTITY_EXCEEDS_PO": 2,
            "QUANTITY_EXCEEDS_RECEIPT": 2,
            "PRICE_MISMATCH": 1,
        },
        "disputed_amounts": {
            "EUR": "2450.00",
            "MAD": "10199.00",
            "USD": "75.00",
        },
    }
    assert len(payload["results"]) == 17
    assert len(request_directories) == 1
    assert not request_directories[0].exists()


def test_invalid_csv_returns_structured_error_without_temporary_path(
    client: TestClient,
    request_directories: list[Path],
) -> None:
    response = client.post(
        "/api/v1/reconcile",
        files=upload_files(purchase_orders=INVALID_PURCHASE_ORDERS),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "message": "Uploaded CSV data failed validation.",
        "issues": [
            {
                "file": "purchase_orders",
                "source": "purchase_orders.csv",
                "row": 2,
                "column": "ordered_quantity",
                "value": "-3",
                "reason": "ordered_quantity must be a finite decimal greater than zero",
            }
        ],
    }
    assert "reconcile-api-test" not in response.text
    assert len(request_directories) == 1
    assert not request_directories[0].exists()


@pytest.mark.parametrize("missing_field", SAMPLE_FILES)
def test_missing_upload_returns_422_without_running_reconciliation(
    missing_field: str,
    monkeypatch: pytest.MonkeyPatch,
    request_directories: list[Path],
) -> None:
    def fail_if_called(*paths: Path) -> str:
        pytest.fail("reconciliation should not run when a required upload is missing")

    monkeypatch.setattr(web_app, "_render_reconciliation", fail_if_called)
    files = upload_files()
    files.pop(missing_field)

    with TestClient(create_app()) as test_client:
        response = test_client.post("/api/v1/reconcile", files=files)

    assert response.status_code == 422
    assert any(error["loc"][-1] == missing_field for error in response.json()["detail"])
    assert request_directories == []


def test_oversized_upload_returns_413_without_running_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    request_directories: list[Path],
) -> None:
    limit = 64

    def fail_if_called(*paths: Path) -> str:
        pytest.fail("reconciliation should not run for an oversized upload")

    monkeypatch.setattr(web_app, "_render_reconciliation", fail_if_called)

    with TestClient(create_app(max_upload_bytes=limit)) as test_client:
        response = test_client.post(
            "/api/v1/reconcile",
            files=upload_files(purchase_orders=b"x" * (limit + 1)),
        )

    assert web_app.MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert response.status_code == 413
    assert response.json() == {
        "error": "file_too_large",
        "file": "purchase_orders",
        "max_bytes": limit,
    }
    assert len(request_directories) == 1
    assert not request_directories[0].exists()


def test_client_filenames_never_control_temporary_paths(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    request_directories: list[Path],
) -> None:
    captured_paths: list[Path] = []
    original_render = web_app._render_reconciliation

    def capture_paths(*paths: Path) -> str:
        captured_paths.extend(paths)
        return original_render(*paths)

    monkeypatch.setattr(web_app, "_render_reconciliation", capture_paths)
    filenames = {
        "purchase_orders": "../../evil.csv",
        "receipts": "..\\..\\evil.csv",
        "invoices": "not-even-a-csv.exe",
    }

    response = client.post(
        "/api/v1/reconcile",
        files=upload_files(filenames=filenames),
    )

    assert response.status_code == 200
    assert [path.name for path in captured_paths] == [
        "purchase_orders.csv",
        "goods_receipts.csv",
        "invoices.csv",
    ]
    assert {path.parent for path in captured_paths} == {request_directories[0]}
    assert all(not path.exists() for path in captured_paths)
    assert not request_directories[0].exists()


def test_unexpected_failure_returns_generic_500_and_cleans_uploads(
    monkeypatch: pytest.MonkeyPatch,
    request_directories: list[Path],
) -> None:
    def fail_with_sensitive_detail(*paths: Path) -> str:
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr(web_app, "_render_reconciliation", fail_with_sensitive_detail)

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        response = test_client.post("/api/v1/reconcile", files=upload_files())

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "Internal server error.",
    }
    assert "sensitive internal detail" not in response.text
    assert len(request_directories) == 1
    assert not request_directories[0].exists()
