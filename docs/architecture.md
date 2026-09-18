# Architecture

## Scope of this milestone

The foundation only: monorepo layout, a FastAPI service with `GET /health`,
PostgreSQL via Docker Compose, SQLAlchemy and Alembic configuration, a minimal
SDK, and a minimal Next.js app.

Explicitly **not** built yet: replay, evaluation, semantic comparison, CI/CD
integration, billing, authentication, AWS, Kubernetes, and any AI features.

## Repository layout

```
agenttrace/
├── apps/
│   ├── api/              FastAPI service
│   └── web/              Next.js app
├── packages/
│   └── python-sdk/       `agenttrace` SDK, installed into agent processes
├── examples/             Runnable SDK examples
├── docs/                 This documentation
└── docker-compose.yml    Local PostgreSQL
```

## API module boundaries

Dependencies point inward: transport depends on services, services depend on
the database and schemas, and nothing depends on transport.

| Layer | Module | Rule |
| --- | --- | --- |
| Transport | `app/api/` | Routers and dependency wiring. No business logic. |
| Contracts | `app/schemas/` | Pydantic models forming the public API shape. |
| Services | `app/services/` | Business logic. Unaware of FastAPI. |
| Data | `app/db/` | Declarative base, engine, session lifecycle. |
| Config | `app/config.py` | The only module that reads the environment. |

`GET /health` demonstrates the split: the handler resolves a `HealthService`,
asks it for a report, and maps the report to a status code. The decision about
what "healthy" means lives in the service.

## Configuration

Every setting comes from the environment, via `pydantic-settings`. There is no
default for `POSTGRES_PASSWORD` — a missing credential fails at startup rather
than silently falling back. `Settings.database_url` is a plain property rather
than a `computed_field` so the password cannot reach `repr()` or
`model_dump()`, and health-check errors are summarised rather than echoed, so
the DSN never appears in a response body.

## Database and migrations

SQLAlchemy 2.x with the async engine (`asyncpg`). `app/db/base.py` holds the
declarative base and an explicit constraint naming convention so Alembic emits
deterministic, reversible names.

Alembic reads its URL from the same settings object as the application, so
`alembic.ini` contains no credentials. `app/migrations/env.py` runs migrations
through the async engine. No revisions exist yet: no models have been defined.

## SDK

`packages/python-sdk` has **no runtime dependencies**. It is imported into the
user's agent process, so it must not constrain their dependency tree. Traces
are held in memory for now; transport to the API is a later milestone, and the
public surface is intended to survive that change.
