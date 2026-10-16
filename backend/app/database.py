"""
SQLAlchemy database setup.
Supports both SQLite (development) and PostgreSQL (production) via DATABASE_URL.
"""
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _build_engine():
    """Build SQLAlchemy engine with appropriate settings for the database type."""
    url = settings.DATABASE_URL

    if url.startswith("sqlite"):
        from sqlalchemy.pool import NullPool, StaticPool

        poolclass = StaticPool if ":memory:" in url else NullPool
        # SQLite requires check_same_thread=False for use with FastAPI
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=poolclass,
            echo=False,
        )

        # Enable WAL mode, foreign keys, and busy timeout for SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    else:
        # PostgreSQL and other databases
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )


engine = _build_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.
    Ensures the session is always closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Create all database tables. Called on application startup."""
    Base.metadata.create_all(bind=engine)
