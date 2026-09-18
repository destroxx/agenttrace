/**
 * Typed client for the API's health endpoint.
 *
 * Kept out of the component so the fetch/parse logic stays testable and the
 * component only deals with rendering.
 */

import { apiBaseUrl } from "@/lib/config";

export type ComponentStatus = "up" | "down";
export type OverallStatus = "ok" | "degraded";

export interface ComponentHealth {
  status: ComponentStatus;
  latency_ms: number | null;
  error: string | null;
}

export interface HealthReport {
  status: OverallStatus;
  version: string;
  environment: string;
  checks: Record<string, ComponentHealth>;
}

export type HealthResult =
  | { ok: true; report: HealthReport }
  | { ok: false; error: string };

/**
 * Fetch the API health report.
 *
 * A degraded API answers 503 with a valid body, so a non-2xx response is still
 * parsed rather than treated as a transport failure.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResult> {
  try {
    const response = await fetch(`${apiBaseUrl}/health`, {
      signal,
      cache: "no-store",
    });
    const report = (await response.json()) as HealthReport;
    return { ok: true, report };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}
