"""Schemas shared across resources."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Page[ItemT](BaseModel):
    """One page of results, plus enough metadata to request the next."""

    items: list[ItemT]
    total: int = Field(description="Total rows matching the query, across all pages.")
    page: int = Field(description="1-based page number.")
    page_size: int


class ErrorResponse(BaseModel):
    """The body returned for a handled error."""

    detail: str
