"""Private database configuration and explicit transaction-local tenant context."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

DATABASE_URL_ENV = "DATABASE_URL"
TENANT_SETTING = "app.current_organization_id"
RUNTIME_GROUP = "reconcile_runtime"


def database_url(value: str | None = None) -> URL:
    configured = value if value is not None else os.environ.get(DATABASE_URL_ENV, "")
    try:
        url = make_url(configured)
        if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.database:
            raise ValueError
        return url.set(drivername="postgresql+psycopg")
    except (ValueError, TypeError, ArgumentError):
        raise ValueError(
            "DATABASE_URL must configure a PostgreSQL database using psycopg."
        ) from None


def database_engine(value: str | None = None, *, pool_size: int = 5) -> Engine:
    return create_engine(
        database_url(value),
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        hide_parameters=True,
        echo=False,
    )


@contextmanager
def tenant_session(engine: Engine, organization_id: UUID) -> Iterator[Session]:
    """Use only after a service has verified the caller's organization membership."""
    if not isinstance(organization_id, UUID):
        raise ValueError("A verified organization UUID is required")
    with Session(engine) as session, session.begin():
        session.execute(
            text("SELECT set_config(:setting, :organization, true)"),
            {"setting": TENANT_SETTING, "organization": str(organization_id)},
        )
        yield session
