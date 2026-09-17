"""Bounded dependency probes for deployment readiness."""

import asyncio

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine, text

from reconcile.auth.runtime import AuthRuntime


def _probe(engine: Engine, timeout_seconds: float) -> None:
    statement_timeout = max(1, int(timeout_seconds * 1000))
    with engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{statement_timeout}ms"},
        )
        if connection.scalar(text("SELECT 1")) != 1:
            raise RuntimeError("Database readiness probe failed")


async def databases_ready(runtime: AuthRuntime) -> bool:
    timeout = runtime.settings.readiness_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            await asyncio.gather(
                run_in_threadpool(_probe, runtime.identity, timeout),
                run_in_threadpool(_probe, runtime.tenant, timeout),
            )
    except Exception:
        return False
    return True
