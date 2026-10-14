from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import DateTime, ForeignKey, MetaData, String, func
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> str:
    return str(uuid.uuid4())


def rowcount(result: Result[Any]) -> int:
    """Rows affected by a DML statement.

    ``Session.execute`` is typed as returning ``Result``, but for INSERT/UPDATE/DELETE it is a ``CursorResult``.
    """
    return cast("CursorResult[Any]", result).rowcount


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: dict[Any, Any] = {datetime: DateTime(timezone=True)}


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserOwned:
    """Every row of personal data belongs to exactly one user; all queries filter on it."""

    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
