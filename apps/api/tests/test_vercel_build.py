"""Tests for the Vercel build step's one decision: whether to migrate.

Getting it wrong is the expensive direction: a preview that migrated the
production database would apply an unmerged branch's schema to live data.
"""

from __future__ import annotations

import pytest

from scripts.vercel_build import should_migrate


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"VERCEL_ENV": "production"}, True),
        ({"VERCEL_ENV": "production", "AGENTTRACE_MIGRATE_PREVIEWS": "0"}, True),
        ({"VERCEL_ENV": "preview"}, False),
        ({"VERCEL_ENV": "preview", "AGENTTRACE_MIGRATE_PREVIEWS": "1"}, True),
        ({"VERCEL_ENV": "preview", "AGENTTRACE_MIGRATE_PREVIEWS": "true"}, False),
        ({"VERCEL_ENV": "development"}, False),
        ({}, False),
    ],
    ids=[
        "production",
        "production-ignores-preview-flag",
        "preview",
        "preview-with-own-database",
        "preview-flag-must-be-1",
        "vercel-dev",
        "not-on-vercel",
    ],
)
def test_only_production_migrates_unless_previews_opt_in(
    environ: dict[str, str], expected: bool
) -> None:
    migrate, reason = should_migrate(environ)

    assert migrate is expected
    assert reason
