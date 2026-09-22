# AgentTrace — conventions

Record-and-replay regression testing for AI agents: record real agent runs
(tool calls and their responses), then replay them against a newer agent
without calling the real tools.

Phase status lives in `README.md`, not here, so this file does not go stale.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.x async + asyncpg, Alembic, PostgreSQL 16
via Compose. Next.js + TypeScript + Tailwind + shadcn/ui. pytest, ruff (line
length 100).

## Layout

`apps/api/` FastAPI service · `apps/web/` Next.js app (has its own CLAUDE.md) ·
`packages/python-sdk/` the SDK, installed into user agent processes ·
`examples/` runnable examples · `docs/architecture.md` design decisions and
trade-offs, keep current.

## API layering

Dependencies point inward. Nothing depends on transport.

| Layer | Module | Rule |
| --- | --- | --- |
| Transport | `app/api/` | Routers and dependency wiring. **No business logic.** |
| Contracts | `app/schemas/` | Pydantic. Always separate from the ORM. |
| Services | `app/services/` | Business logic. **Never imports FastAPI.** |
| Data | `app/models/`, `app/db/` | ORM, engine, session lifecycle |
| Config | `app/config.py` | The only module that reads the environment |

Services raise only `NotFoundError` / `ConflictError` from
`app/services/exceptions.py`; handlers in `app/main.py` map those to 404/409.
`HTTPException` appears nowhere under `app/`. Routes declare their
`responses={404: ..., 409: ...}`. Eager-load relationships (`selectinload`) —
a lazy load in async context raises. `runs.metadata` is mapped as
`run_metadata`; never read `run.metadata` off the ORM, that is SQLAlchemy's
schema registry.

## SDK rules

- **Standard library only at runtime.** It is imported into someone else's
  agent process and must not constrain their dependency tree. `urllib` for
  HTTP; `asyncio.to_thread` to keep blocking calls off the event loop.
- **Never raise into user code.** Tool results and exceptions pass through
  unchanged. Recording and upload failures are logged to
  `logging.getLogger("agenttrace")` and swallowed. Catch `Exception`, never
  `BaseException`, except where a handler re-raises immediately — the one
  exception is the decorator's recording of a cancelled tool.
- Plain dataclasses with `slots=True`. Prefer `asyncio.run()` in tests over
  adding pytest-asyncio.

## Style

Docstrings and comments explain **why**, not what — match `app/services/runs.py`.
Reuse existing Field constraints rather than redefining them. No credential has
a default anywhere; secrets are `SecretStr` and the DSN is a plain property.

## Commands

```bash
cd apps/api && RUN_INTEGRATION_TESTS=1 pytest -o addopts=""   # 0 skipped in CI
cd packages/python-sdk && pytest -o addopts=""
ruff check apps/api packages/python-sdk examples
cd apps/web && npm run lint && npm run build && npx tsc --noEmit   # build before tsc
cd apps/api && alembic upgrade head && alembic downgrade base && alembic upgrade head && alembic check
```

`pyproject.toml` sets `addopts = "-q"`, so `-o addopts=""` is needed for a
per-test listing.

## Workflow

- **One phase at a time.** Do what it asks and stop; never start the next one.
- **Never commit or push** unless explicitly asked.
- **Never write review, diff or scratch files inside the repository.** `git add
  -A` has swept scratch files into a commit before — check `git status` first.
- **Report differences instead of guessing.** If the prompt and the code
  disagree, follow the code and say so. If a phase is scoped to certain
  directories, do not touch the others — report bugs found there.
- Verify before claiming done: run the commands above and paste real output.
