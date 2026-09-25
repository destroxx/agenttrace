/**
 * Display formatting. Rendered on the server, so it avoids the server's own
 * locale and time zone: every timestamp is shown in UTC, the zone the API
 * stores, and says so.
 */

export function formatTimestamp(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return `${date.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return "—";
  }
  if (ms < 1000) {
    return `${ms} ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/** Wall-clock time between two timestamps, for a run's header. */
export function durationBetween(start: string, end: string | null): number | null {
  if (!end) {
    return null;
  }
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Number.isNaN(ms) ? null : Math.max(0, ms);
}

/** First block of a UUID: enough to tell runs apart in a table, and to search for. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}
