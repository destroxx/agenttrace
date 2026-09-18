"""Declarative base for all ORM models.

Models are introduced in a later milestone. This module exists now so that the
metadata object Alembic autogenerates against has a single, stable home.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit naming convention so that Alembic emits deterministic, reversible
# names for indexes and constraints instead of backend-generated ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class every AgentTrace ORM model inherits from."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
