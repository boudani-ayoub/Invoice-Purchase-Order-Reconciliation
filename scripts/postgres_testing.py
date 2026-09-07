"""Own a disposable database and three restricted roles, never reset an existing database."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, create_engine

from reconcile.auth.config import IDENTITY_GROUP
from reconcile.persistence.session import RUNTIME_GROUP, database_url


@dataclass
class Database:
    admin: Engine
    runtime: Engine
    migration_url: str = field(repr=False)
    identity: Engine


@contextmanager
def provision_database(configured: str, *, revision: str = "head"):
    admin_url = database_url(configured)
    suffix = uuid4().hex[:16]
    db_name, owner, runtime, identity = (
        f"reconcile_test_{suffix}{tail}" for tail in ("", "_owner", "_runtime", "_identity")
    )
    password = uuid4().hex
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    created_roles = []
    created_database = False
    engines = []
    try:
        with admin.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            for group in (RUNTIME_GROUP, IDENTITY_GROUP):
                if not cursor.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (group,)
                ).fetchone():
                    cursor.execute(
                        sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
                            sql.Identifier(group)
                        )
                    )
            for role in (owner, runtime, identity):
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                created_roles.append(role)
                group = IDENTITY_GROUP if role == identity else RUNTIME_GROUP
                cursor.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role))
                )
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(db_name), sql.Identifier(owner)
                )
            )
            created_database = True
        owner_url = admin_url.set(database=db_name, username=owner, password=password)
        data_admin = create_engine(admin_url.set(database=db_name), hide_parameters=True)
        engines.append(data_admin)
        runtime_engine = create_engine(
            admin_url.set(database=db_name, username=runtime, password=password),
            pool_size=1,
            max_overflow=0,
            hide_parameters=True,
        )
        engines.append(runtime_engine)
        identity_engine = create_engine(
            admin_url.set(database=db_name, username=identity, password=password),
            pool_size=3,
            max_overflow=0,
            hide_parameters=True,
        )
        engines.append(identity_engine)
        migration_url = owner_url.render_as_string(hide_password=False)
        with patch.dict(os.environ, {"DATABASE_URL": migration_url}):
            command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), revision)
        yield Database(data_admin, runtime_engine, migration_url, identity_engine)
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            if created_database:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db_name))
                )
            for role in reversed(created_roles):
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        admin.dispose()
