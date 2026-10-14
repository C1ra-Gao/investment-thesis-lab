"""Forward-only M1 bootstrap migration, checked by PRAGMA user_version.

Schema version 1 is append-only. Future versions require explicit migrations;
create_all is not claimed to be an ALTER TABLE or PostgreSQL migration engine.
"""

from sqlalchemy import text
from .schema import Base

VERSION = 1


def upgrade(engine) -> None:
    if engine.dialect.name != "sqlite":
        raise ValueError("M1 currently supports SQLite only; PostgreSQL not validated")
    with engine.begin() as connection:
        existing = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
        if existing not in (0, VERSION):
            raise ValueError("unsupported_database_schema_version")
        Base.metadata.create_all(connection)
        connection.execute(text("INSERT OR IGNORE INTO schema_version(version) VALUES (1)"))
        # Names come exclusively from fixed application metadata, never user input.
        for table in Base.metadata.tables:
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER IF NOT EXISTS "immutable_{table}_{operation.lower()}" '
                    f'BEFORE {operation} ON "{table}" BEGIN '
                    "SELECT RAISE(ABORT, 'append_only_record'); END"
                )
        connection.exec_driver_sql("PRAGMA user_version = 1")
