# AgentTrace Web

Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui. See the
[repository README](../../README.md) for the full local setup.

## Layout

| Path | Responsibility |
| --- | --- |
| `src/app/` | Routes and layout |
| `src/components/` | Application components |
| `src/components/ui/` | shadcn/ui primitives |
| `src/components/site/` | Product-site sections; the replay lab and dashboard preview hold real output of `examples/replay_demo.py` and `examples/async_support_agent.py` — re-run them and update the data when the comparison engine changes |
| `src/lib/config.ts` | Environment-driven configuration |
| `src/lib/health.ts` | Typed client for the API health endpoint |

## Run

```bash
cp .env.example .env.local
npm install
npm run dev
```

Two route groups, each with its own chrome under the shared root layout:

| Route group | URLs | What it is |
| --- | --- | --- |
| `src/app/(site)/` | `/` | Product site. Always dark, static, never calls the API |
| `src/app/(dashboard)/` | `/projects`, `/projects/[id]`, `/runs/[id]`, `/runs/[id]/comparison` | Read-only dashboard; follows the OS theme |

Theme tokens (including `signal`, `pass`, `warn`, `fail`) live in
`src/app/globals.css`. A page that cannot reach the API shows the live health
card; its "Check again" button refetches from the browser, which is why the API
allows the `http://localhost:3000` origin via `CORS_ALLOW_ORIGINS`.

After moving or renaming route folders, restart `npm run dev`: a running dev
server keeps the old routes and writes stale types to `.next/dev/types`, which
then fail `npm run build`.

## Checks

```bash
npm run lint
npx tsc --noEmit
npm run build
```
