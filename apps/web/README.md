# AgentTrace Web

Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui. See the
[repository README](../../README.md) for the full local setup.

## Layout

| Path | Responsibility |
| --- | --- |
| `src/app/` | Routes and layout |
| `src/components/` | Application components |
| `src/components/ui/` | shadcn/ui primitives |
| `src/lib/config.ts` | Environment-driven configuration |
| `src/lib/health.ts` | Typed client for the API health endpoint |

## Run

```bash
cp .env.example .env.local
npm install
npm run dev
```

The home page reports API and database status. The initial report is fetched on
the server; the "Check again" button refetches from the browser, which is why
the API allows the `http://localhost:3000` origin via `CORS_ALLOW_ORIGINS`.

## Checks

```bash
npm run lint
npx tsc --noEmit
npm run build
```
