/**
 * The API health indicator in the site header: a dot and a word.
 *
 * Streams in behind a Suspense boundary, so a slow health check never holds
 * up the page it sits on. The full card, with a re-check button, appears on
 * any page that could not reach the API.
 */

import { apiBaseUrl } from "@/lib/config";
import { fetchHealth } from "@/lib/health";

export async function HealthIndicator() {
  const result = await fetchHealth(AbortSignal.timeout(3000));
  const [tone, label, detail] = !result.ok
    ? ["bg-destructive", "API unreachable", result.error]
    : result.report.status === "ok"
      ? ["bg-emerald-500", "API healthy", `v${result.report.version} · ${result.report.environment}`]
      : [
          "bg-amber-500",
          "API degraded",
          `database ${result.report.checks.database?.status ?? "unknown"}`,
        ];
  return (
    <span
      className="flex items-center gap-2 text-xs text-muted-foreground"
      title={`${apiBaseUrl}/health — ${detail}`}
    >
      <span className={`size-2 rounded-full ${tone}`} aria-hidden />
      {label}
    </span>
  );
}

export function HealthIndicatorFallback() {
  return (
    <span className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="size-2 rounded-full bg-muted-foreground/40" aria-hidden />
      Checking API…
    </span>
  );
}
