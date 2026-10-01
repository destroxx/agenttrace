"""The API's build step on Vercel: bring the database schema up to date.

    python -m scripts.vercel_build

Vercel runs it after installing dependencies and before the deployment goes
live (`[tool.vercel.scripts] build` in pyproject.toml), so a deployment never
serves code newer than its schema, and a migration that fails stops the
deployment instead of breaking the live one.

Only production migrates by default. A preview deployment is code from an
unmerged branch; run against the production database, its migrations would
change production's schema before anyone approved them. Set
`AGENTTRACE_MIGRATE_PREVIEWS=1` for the Preview environment only when each
preview has its own database -- such as a Neon branch per deployment -- and
previews then migrate that copy.
"""

from __future__ import annotations

import os
import subprocess
import sys


def should_migrate(environ: dict[str, str]) -> tuple[bool, str]:
    """Whether this build migrates, and the reason, for the build log."""
    vercel_env = environ.get("VERCEL_ENV", "")
    if vercel_env == "production":
        return True, "production deployment"
    if vercel_env == "preview" and environ.get("AGENTTRACE_MIGRATE_PREVIEWS") == "1":
        return True, "preview deployment with its own database (AGENTTRACE_MIGRATE_PREVIEWS=1)"
    if vercel_env == "preview":
        return False, "preview deployment sharing the production database"
    return False, f"not a Vercel deployment build (VERCEL_ENV={vercel_env or 'unset'})"


def main() -> int:
    migrate, reason = should_migrate(dict(os.environ))
    if not migrate:
        print(f"agenttrace: skipping migrations: {reason}", flush=True)
        return 0
    print(f"agenttrace: running migrations: {reason}", flush=True)
    # A subprocess rather than alembic's Python API: the command is exactly
    # the one CLAUDE.md and CI run, and its exit code is the build's.
    return subprocess.run(["alembic", "upgrade", "head"], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
