/**
 * A run's events as steps: one row per tool call (its call and its answer
 * together), one row per event that belongs to no call.
 *
 * The span column draws each step across the run's sequence range, so calls
 * that were in flight at the same time show as overlapping bars one above the
 * other — parallelism is visible without reading sequence numbers. Rows
 * expand with a native <details>; there is no client JavaScript here.
 */

import { Tag } from "@/components/badges";
import { Panel } from "@/components/brand/primitives";
import { JsonBlock } from "@/components/json-view";
import type { RunEvent } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { buildTimeline, type EventStep, type Timeline, type ToolStep } from "@/lib/timeline";

// Distinguishes lanes of concurrent steps; lane 0 (ran alone) stays neutral.
// The landing page's picture of this page draws its bars with these too.
export const LANE_COLOURS = [
  "bg-foreground/60",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
];
const GRID = "grid grid-cols-[4.5rem_minmax(0,1fr)_5rem_minmax(6rem,14rem)] items-center gap-3";
const SUMMARY = `${GRID} cursor-pointer list-none px-4 py-2 text-[13px] transition-colors hover:bg-card [&::-webkit-details-marker]:hidden`;
const DETAIL = "grid gap-3 border-t bg-background/60 px-4 py-4 md:grid-cols-2";

export function RunTimeline({ events }: { events: RunEvent[] }) {
  if (events.length === 0) {
    return <p className="text-[13px] text-muted-foreground">This run recorded no events.</p>;
  }
  const timeline = buildTimeline(events);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs leading-6 text-muted-foreground">
        {events.length} events as {timeline.steps.length} steps
        {timeline.parallelSteps > 0
          ? ` · ${timeline.parallelSteps} steps ran in parallel (overlapping bars)`
          : " · no parallel calls"}
        . Positions are event sequence numbers.
      </p>
      <Panel>
        <div className="overflow-x-auto">
          <div className="min-w-[40rem]">
            <div className={`${GRID} border-b bg-muted/50 px-4 py-2.5 text-[10px] tracking-[0.18em] text-muted-foreground uppercase`}>
              <span>seq</span>
              <span>step</span>
              <span className="text-right">duration</span>
              <span>span</span>
            </div>
            {timeline.steps.map((step) =>
              step.kind === "tool" ? (
                <ToolRow key={step.key} step={step} timeline={timeline} />
              ) : (
                <EventRow key={step.key} step={step} timeline={timeline} />
              ),
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}

function ToolRow({ step, timeline }: { step: ToolStep; timeline: Timeline }) {
  const parallel = step.concurrentWith.length > 0;
  return (
    <details className="group border-t first-of-type:border-t-0">
      <summary className={SUMMARY}>
        <span className="text-xs tabular-nums text-muted-foreground">
          {step.start}
          {step.end !== null ? `-${step.end}` : "-?"}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <Chevron />
          <span className="font-medium">{step.toolName ?? "(unnamed tool)"}</span>
          <OutcomeBadge outcome={step.outcome} />
          {parallel ? (
            <span
              className="border px-1.5 text-[10px] text-muted-foreground"
              title={`Open at the same time as ${step.concurrentWith
                .map((other) => `${other.toolName} (seq ${other.start})`)
                .join(", ")}`}
            >
              parallel with{" "}
              {step.concurrentWith.map((other) => `${other.toolName} #${other.start}`).join(", ")}
            </span>
          ) : null}
        </span>
        <span className="text-right text-xs tabular-nums">
          {formatDuration(step.result?.duration_ms)}
        </span>
        <SpanBar
          timeline={timeline}
          start={step.start}
          end={step.end ?? timeline.last}
          colour={LANE_COLOURS[step.lane % LANE_COLOURS.length]}
          open={step.end === null}
          lane={parallel ? step.lane : null}
        />
      </summary>
      <div className={DETAIL}>
        <Side
          title={`Call${step.call ? ` · seq ${step.call.sequence}` : ""}`}
          empty="No tool_call event was recorded for this call id."
          value={step.call?.arguments}
          present={step.call !== null}
          label="arguments"
        />
        <Side
          title={
            step.result
              ? `${step.result.event_type === "error" ? "Error" : "Response"} · seq ${step.result.sequence}`
              : "Response"
          }
          empty="The call was never answered: the run ended, or the answer was lost."
          value={step.result?.response}
          present={step.result !== null}
          label={step.result?.event_type === "error" ? "error" : "response"}
        />
        <p className="text-xs text-muted-foreground md:col-span-2">
          call_id <code>{step.callId}</code>
        </p>
      </div>
    </details>
  );
}

function EventRow({ step, timeline }: { step: EventStep; timeline: Timeline }) {
  const { event } = step;
  const hasPayload = event.arguments !== null || event.response !== null;
  return (
    <details className="group border-t first-of-type:border-t-0">
      <summary className={SUMMARY}>
        <span className="text-xs tabular-nums text-muted-foreground">
          {event.sequence}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <Chevron />
          <span className={event.event_type === "error" ? "text-fail" : "text-muted-foreground"}>
            {event.event_type}
          </span>
          {event.tool_name ? (
            <span className="text-muted-foreground">{event.tool_name}</span>
          ) : null}
        </span>
        <span className="text-right text-xs tabular-nums">
          {formatDuration(event.duration_ms)}
        </span>
        <SpanBar timeline={timeline} start={event.sequence} end={event.sequence} colour="bg-muted-foreground" lane={null} />
      </summary>
      <div className={DETAIL}>
        {hasPayload ? (
          <>
            {event.arguments !== null ? <Side title="Arguments" value={event.arguments} present label="arguments" /> : null}
            {event.response !== null ? <Side title="Response" value={event.response} present label="response" /> : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">No payload.</p>
        )}
        {event.call_id ? (
          <p className="text-xs text-muted-foreground md:col-span-2">
            call_id <code>{event.call_id}</code> (not paired: another event already
            claimed this call id)
          </p>
        ) : null}
      </div>
    </details>
  );
}

function Side({
  title,
  value,
  present,
  empty,
  label,
}: {
  title: string;
  value: unknown;
  present: boolean;
  empty?: string;
  label: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-[10px] tracking-[0.18em] text-muted-foreground uppercase">{title}</span>
      {present ? (
        <JsonBlock value={value ?? null} className="rounded-md border" />
      ) : (
        <p className="text-xs text-muted-foreground">{empty ?? `No ${label}.`}</p>
      )}
    </div>
  );
}

function SpanBar({
  timeline,
  start,
  end,
  colour,
  open = false,
  lane,
}: {
  timeline: Timeline;
  start: number;
  end: number;
  colour: string;
  open?: boolean;
  lane: number | null;
}) {
  const range = Math.max(1, timeline.last - timeline.first);
  const left = ((start - timeline.first) / range) * 100;
  const width = ((end - start) / range) * 100;
  return (
    <span className="relative block h-4" aria-hidden>
      <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
      <span
        className={`absolute top-1/2 h-2 min-w-2 -translate-y-1/2 ${colour} ${
          open ? "opacity-50" : ""
        }`}
        style={{ left: `${left}%`, width: `${width}%` }}
      />
      {lane !== null ? (
        <span className="absolute -top-0.5 right-0 text-[10px] text-muted-foreground">
          L{lane + 1}
        </span>
      ) : null}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: ToolStep["outcome"] }) {
  if (outcome === "error") {
    return <Tag look="fail">error</Tag>;
  }
  if (outcome === "no_result") {
    return <Tag look="outline">no result</Tag>;
  }
  return null;
}

function Chevron() {
  return (
    <span
      className="inline-block w-3 text-muted-foreground transition-transform group-open:rotate-90"
      aria-hidden
    >
      ›
    </span>
  );
}
