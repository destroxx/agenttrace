/**
 * Turning a run's flat event list into the steps a person reads.
 *
 * The API stores a tool call and its answer as two events that share a
 * `call_id`. Shown one per row, parallel calls interleave — call A, call B,
 * answer B, answer A — and the reader has to pair them by eye. This module
 * pairs them into one step each, and works out which steps were in flight at
 * the same time, which is exactly what `call_id` was recorded for.
 *
 * Positions are event sequence numbers, not timestamps: sequence is the
 * total order the SDK guarantees, while event timestamps are only when the
 * API stored them.
 */

import type { RunEvent } from "@/lib/api";

const RESULT_TYPES = new Set(["tool_response", "error"]);

export interface ToolStep {
  kind: "tool";
  key: string;
  callId: string;
  toolName: string | null;
  call: RunEvent | null;
  result: RunEvent | null;
  /** Sequence of the step's first event. */
  start: number;
  /** Sequence of its answer; null when the call was never answered. */
  end: number | null;
  outcome: "response" | "error" | "no_result";
  /** 0 for a step that ran alone; otherwise its column among concurrent steps. */
  lane: number;
  /** Steps that were open at the same time as this one. */
  concurrentWith: { toolName: string | null; start: number }[];
}

export interface EventStep {
  kind: "event";
  key: string;
  event: RunEvent;
  start: number;
}

export type Step = ToolStep | EventStep;

export interface Timeline {
  steps: Step[];
  first: number;
  last: number;
  parallelSteps: number;
}

export function buildTimeline(events: RunEvent[]): Timeline {
  const ordered = [...events].sort((a, b) => a.sequence - b.sequence);
  const first = ordered[0]?.sequence ?? 0;
  const last = ordered.at(-1)?.sequence ?? 0;

  // The first tool_call and the first answer per call id form the step; any
  // further event under the same id (a malformed or foreign trace) keeps its
  // own row rather than being silently dropped.
  const calls = new Map<string, { call: RunEvent | null; result: RunEvent | null }>();
  const claimed = new Set<string>();
  for (const event of ordered) {
    if (event.call_id === null) {
      continue;
    }
    const pair = calls.get(event.call_id) ?? { call: null, result: null };
    if (event.event_type === "tool_call" && pair.call === null) {
      pair.call = event;
      claimed.add(event.id);
    } else if (RESULT_TYPES.has(event.event_type) && pair.result === null) {
      pair.result = event;
      claimed.add(event.id);
    }
    calls.set(event.call_id, pair);
  }

  const steps: Step[] = [];
  const emitted = new Set<string>();
  for (const event of ordered) {
    const pair = event.call_id !== null ? calls.get(event.call_id) : undefined;
    if (!pair || !claimed.has(event.id)) {
      steps.push({ kind: "event", key: event.id, event, start: event.sequence });
      continue;
    }
    if (emitted.has(event.call_id!)) {
      continue;
    }
    emitted.add(event.call_id!);
    const opener = pair.call ?? pair.result!;
    const answered = pair.call !== null && pair.result !== null;
    steps.push({
      kind: "tool",
      key: `call:${event.call_id}`,
      callId: event.call_id!,
      toolName: pair.call?.tool_name ?? pair.result?.tool_name ?? null,
      call: pair.call,
      result: pair.result,
      start: opener.sequence,
      end: answered ? pair.result!.sequence : null,
      outcome:
        pair.result === null
          ? "no_result"
          : pair.result.event_type === "error"
            ? "error"
            : "response",
      lane: 0,
      concurrentWith: [],
    });
  }

  const parallelSteps = markConcurrency(
    steps.filter((step): step is ToolStep => step.kind === "tool"),
    last,
  );
  return { steps, first, last, parallelSteps };
}

/**
 * Two steps ran in parallel when each opened before the other closed. An
 * unanswered call is treated as open until the end of the run, which is the
 * most it can have overlapped.
 *
 * Lanes are assigned greedily in start order, reusing the lowest lane whose
 * step has closed — the usual interval-colouring pass, so steps that never
 * overlap all stay in lane 0.
 */
function markConcurrency(steps: ToolStep[], last: number): number {
  const closes = (step: ToolStep) => step.end ?? last + 1;
  let parallel = 0;
  for (const step of steps) {
    step.concurrentWith = steps
      .filter(
        (other) =>
          other !== step && other.start < closes(step) && step.start < closes(other),
      )
      .map((other) => ({ toolName: other.toolName, start: other.start }));
    if (step.concurrentWith.length > 0) {
      parallel += 1;
    }
  }

  const laneEnds: number[] = [];
  for (const step of [...steps].sort((a, b) => a.start - b.start)) {
    let lane = laneEnds.findIndex((end) => end <= step.start);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[lane] = closes(step);
    step.lane = lane;
  }
  return parallel;
}
