"""
core/async_db.py
────────────────
Async SQLAlchemy engine + session for the whole stack.

The app — and Alembic, via `connection.run_sync(...)` — all share the
single `DATABASE_URL` (mysql+asyncmy://...) from settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, event, func, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    Mapped,
    Session,
    declarative_base,
    mapped_column,
    with_loader_criteria,
)

from core.config import settings

async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)


AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


Base = declarative_base()


class AuditMixin:
    """Record-metadata columns shared by **every** ORM model.

    Defined once here and mixed into each model (``class X(AuditMixin,
    Base)``) so application developers always get, on any stored record:
    a stable opaque identifier, a soft-delete flag, and UTC timestamps.

    Purely additive — it never touches existing columns, relationships,
    or constraints. ``created_at`` / ``updated_at`` are declared here so
    models that lacked them gain them; a model that already declares
    either column keeps its own definition (the class-level column
    shadows the mixin's), preserving any pre-existing index / default.

    Timestamps are stored as **naive UTC** (``datetime.utcnow``), matching
    the convention already used elsewhere in the codebase.
    ``global_time_at`` is a UTC "global clock" mirror of ``updated_at`` —
    set on insert and refreshed on every update.

    ``record_Identifier`` / ``update_record_Identifier`` are **optional,
    client-generated** sync keys (the mobile app builds them as
    ``Platform+AppVersion+LoginId+TablePrefix+RecordNumber``). The server
    never generates them — it stores whatever the client sends, or NULL.
    ``record_Identifier`` is set once on insert and never changed;
    ``update_record_Identifier`` is (re)written by the client only when
    the record is edited. Both are nullable + indexed (not unique) so
    legacy rows and web-created rows that omit them keep working.
    """

    record_Identifier: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True
    )
    update_record_Identifier: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True
    )
    IsDeleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )
    global_time_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
        nullable=False,
    )


# ─────────────────────────────────────────────────────────────────────
# Soft-delete read filter
# ─────────────────────────────────────────────────────────────────────
# Every ORM SELECT automatically excludes rows with ``IsDeleted = True``
# for any model carrying the AuditMixin — including eager-loaded
# relationships — so soft-deleted records are never returned to the API.
# The rows stay physically in the DB. To deliberately include them (e.g.
# an admin/restore flow), run the statement with
# ``.execution_options(include_deleted=True)``.
@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state) -> None:
    if (
        execute_state.is_select
        and not execute_state.is_column_load
        and not execute_state.is_relationship_load
        and not execute_state.execution_options.get("include_deleted", False)
    ):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                AuditMixin,
                lambda cls: cls.IsDeleted == False,  # noqa: E712
                include_aliases=True,
            )
        )


async def get_async_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession scoped to the request."""
    async with AsyncSessionLocal() as session:
        yield session
