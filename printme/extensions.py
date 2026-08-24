import sqlite3

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ignores FOREIGN KEY constraints unless this is set per
    connection - without it, every ForeignKeyConstraint in the schema
    (Job/PhotoItemRow, PhotoSheet/PhotoSheetItem, ...) is decorative.
    Guarded to SQLite only - CLAUDE.md pins the DB, but this must not
    break a differently-configured DATABASE_URL in local dev."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
