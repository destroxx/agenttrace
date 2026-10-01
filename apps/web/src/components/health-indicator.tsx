/**
 * The API health indicator in the dashboard header: a status light and a
 * word. Below `sm` only the light shows; the word stays for screen readers.
 *
 * Streams in behind a Suspense boundary, so a slow health check never holds
 * up the page it sits on. The full card, with a re-check button, appears on
 * any page that could not reach the API.
 */

import { publicApiUrl } from "@/lib/config";
import { fetchHealth } from "@/lib/health";

export async function HealthIndicator() {
  const result = await fetchHealth(AbortSignal.timeout(3000));
  const [tone, label, detail] = !result.ok
    ? ["bg-fail", "api unreachable", result.error]
    : result.report.status === "ok"
      ? ["bg-pass", "api healthy", `v${result.report.version} · ${result.report.environment}`]
      : [
          "bg-warn",
          "api degraded",
          `database ${result.report.checks.database?.status ?? "unknown"}`,
        ];
  return (
    <span
      className="flex items-center gap-2 text-xs text-muted-foreground"
      title={`${publicApiUrl}/health: ${detail}`}
    >
      <span className={`animate-trace size-2 rounded-full ${tone}`} aria-hidden />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </span>
  );
}

export function HealthIndicatorFallback() {
  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="size-2 rounded-full bg-muted-foreground/40" aria-hidden />
      <span className="sr-only sm:not-sr-only">checking api…</span>
    </span>
  );
}
