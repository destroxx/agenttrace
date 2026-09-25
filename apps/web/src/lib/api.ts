/**
 * Typed, read-only client for the AgentTrace API.
 *
 * Called from Server Components. Every function returns an `ApiResult`
 * instead of throwing, because an unreachable API is the normal state of a
 * local checkout with only the web app running — a page should say so
 * plainly, not fall into an error boundary. In production builds Next.js
 * also replaces a thrown Server Component error's message with a generic
 * one, so a thrown "cannot reach the API" would not even be readable.
 */

import { apiBaseUrl } from "@/lib/config";

// A dashboard page waits on these before it can render anything, so a hung
// API must fail fast rather than hold the request open.
const TIMEOUT_MS = 5000;

export type Json =
  | string
  | number
  | boolean
  | null
  | Json[]
  | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary extends Project {
  run_count: number;
  last_run_at: string | null;
}

export const RUN_STATUSES = ["running", "completed", "failed"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];
export type Verdict = "pass" | "fail";

export interface Run {
  id: string;
  project_id: string;
  agent_name: string;
  agent_version: string | null;
  input: JsonObject;
  output: JsonObject | null;
  metadata: JsonObject | null;
  status: RunStatus;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  replay_of_run_id: string | null;
}

export interface RunSummary extends Run {
  event_count: number;
  duration_ms: number | null;
  verdict: Verdict | null;
}

export interface RunEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  call_id: string | null;
  tool_name: string | null;
  arguments: JsonObject | null;
  response: Json;
  duration_ms: number | null;
  created_at: string;
}

export type Severity = "error" | "warning" | "info";
export const SEVERITIES: readonly Severity[] = ["error", "warning", "info"];

export interface Finding {
  code: string;
  severity: Severity;
  message: string;
  details: JsonObject;
}

/** `ComparisonReport.to_dict()` from the SDK, stored verbatim. */
export interface ComparisonReport {
  verdict: Verdict;
  recording_run_id: string;
  replay_run_id: string;
  counts: {
    by_severity: Partial<Record<Severity, number>>;
    by_code: Record<string, number>;
  };
  findings: Finding[];
}

export interface Comparison {
  id: string;
  replay_run_id: string;
  recording_run_id: string;
  verdict: Verdict;
  report: ComparisonReport;
  created_at: string;
}

export type ApiFailure =
  | { kind: "unreachable"; message: string }
  | { kind: "not_found"; message: string }
  | { kind: "error"; status: number; message: string };

export type ApiResult<T> = { ok: true; data: T } | ({ ok: false } & ApiFailure);

async function get<T>(path: string): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      // Runs change underneath the dashboard; never serve a cached page of them.
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    return {
      ok: false,
      kind: "unreachable",
      message: describeNetworkError(error),
    };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return {
      ok: false,
      kind: "error",
      status: response.status,
      message: `GET ${path} answered ${response.status} with a body that is not JSON.`,
    };
  }

  if (response.ok) {
    return { ok: true, data: body as T };
  }
  const message = detailOf(body) ?? `GET ${path} answered ${response.status}.`;
  if (response.status === 404) {
    return { ok: false, kind: "not_found", message };
  }
  return { ok: false, kind: "error", status: response.status, message };
}

function describeNetworkError(error: unknown): string {
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return `no answer within ${TIMEOUT_MS / 1000} s`;
  }
  if (error instanceof Error) {
    // Node's fetch hides the useful part ("ECONNREFUSED") in `cause`.
    const cause = (error as Error & { cause?: { code?: string } }).cause;
    return cause?.code ? `${error.message} (${cause.code})` : error.message;
  }
  return "unknown network error";
}

function detailOf(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return null;
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item ? String(item.msg) : "",
      )
      .filter(Boolean)
      .join("; ");
  }
  return null;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function listProjects(page = 1): Promise<ApiResult<Page<ProjectSummary>>> {
  return get(`/api/v1/projects${query({ page })}`);
}

export function getProject(id: string): Promise<ApiResult<Project>> {
  return get(`/api/v1/projects/${encodeURIComponent(id)}`);
}

export function listRuns(
  projectId: string,
  { page = 1, status }: { page?: number; status?: RunStatus },
): Promise<ApiResult<Page<RunSummary>>> {
  return get(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs${query({ page, status })}`,
  );
}

export function getRun(id: string): Promise<ApiResult<Run>> {
  return get(`/api/v1/runs/${encodeURIComponent(id)}`);
}

export function listEvents(runId: string): Promise<ApiResult<RunEvent[]>> {
  return get(`/api/v1/runs/${encodeURIComponent(runId)}/events`);
}

/** The run's comparison report; `not_found` when the run exists but has none. */
export function getComparison(runId: string): Promise<ApiResult<Comparison>> {
  return get(`/api/v1/runs/${encodeURIComponent(runId)}/comparison`);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Ids in URLs are UUIDs; anything else cannot name a row, so it is a 404 here. */
export function isUuid(value: string): boolean {
  return UUID.test(value);
}
