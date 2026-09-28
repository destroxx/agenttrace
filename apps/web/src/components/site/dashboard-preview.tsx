/**
 * A static picture of the dashboard's run page, drawn in HTML rather than a
 * screenshot so it stays sharp and themed. The steps are a real trace of
 * `examples/async_support_agent.py` (14 events, sequences 0 to 13); the bars use
 * the same sequence-based geometry as `components/timeline.tsx`.
 */

const FIRST = 0;
const LAST = 13;

type Step =
  | { kind: "event"; seq: number; name: string }
  | { kind: "tool"; start: number; end: number; name: string; ms: number; lane: 0 | 1 | 2 };

const STEPS: Step[] = [
  { kind: "event", seq: 0, name: "agent_start" },
  { kind: "tool", start: 1, end: 2, name: "get_customer", ms: 50, lane: 0 },
  { kind: "tool", start: 3, end: 5, name: "get_order", ms: 50, lane: 1 },
  { kind: "tool", start: 4, end: 6, name: "get_order", ms: 50, lane: 2 },
  { kind: "tool", start: 7, end: 8, name: "get_delivery_status", ms: 51, lane: 0 },
  { kind: "tool", start: 9, end: 10, name: "get_delivery_status", ms: 51, lane: 0 },
  { kind: "tool", start: 11, end: 12, name: "format_reply", ms: 0, lane: 0 },
  { kind: "event", seq: 13, name: "agent_end" },
];

const LANE = ["bg-foreground/60", "bg-chart-2", "bg-chart-3"];
const GRID = "grid grid-cols-[3.5rem_minmax(0,1fr)_3.5rem_minmax(5rem,11rem)] items-center gap-3";

function Bar({ start, end, colour }: { start: number; end: number; colour: string }) {
  const range = LAST - FIRST;
  return (
    <span className="relative block h-4" aria-hidden>
      <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
      <span
        className={`absolute top-1/2 h-2 min-w-2 -translate-y-1/2 ${colour}`}
        style={{ left: `${((start - FIRST) / range) * 100}%`, width: `${((end - start) / range) * 100}%` }}
      />
    </span>
  );
}

export function DashboardPreview() {
  return (
    <figure className="overflow-hidden rounded-md border bg-code">
      <div className="flex items-center gap-3 border-b bg-card px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 bg-muted-foreground/30" />
          <span className="size-2.5 bg-muted-foreground/30" />
          <span className="size-2.5 bg-muted-foreground/30" />
        </span>
        <span className="flex-1 truncate border bg-background px-3 py-1 font-mono text-[11px] text-muted-foreground">
          localhost:3000/runs/aedff5c5…
        </span>
      </div>

      <div className="flex flex-col gap-4 p-4 sm:p-6">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-[11px] text-muted-foreground">Projects / Demo</p>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-2xl font-extrabold">support-agent</h3>
            <span className="bg-secondary px-2 py-0.5 text-xs">completed</span>
            <span className="border px-2 py-0.5 font-mono text-xs">v1.0.0</span>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          14 events as 8 steps · 2 steps ran in parallel (overlapping bars)
        </p>

        <div className="overflow-x-auto border bg-card">
          <div className="min-w-[34rem]">
            <div className={`${GRID} border-b bg-muted/50 px-4 py-2 font-mono text-[10px] tracking-wider text-muted-foreground uppercase`}>
              <span>Seq</span>
              <span>Step</span>
              <span className="text-right">Dur.</span>
              <span>Span</span>
            </div>
            {STEPS.map((step) =>
              step.kind === "event" ? (
                <div key={step.seq} className={`${GRID} border-t px-4 py-1.5 text-xs first:border-t-0`}>
                  <span className="font-mono text-muted-foreground">{step.seq}</span>
                  <span className="text-muted-foreground">{step.name}</span>
                  <span className="text-right text-muted-foreground" />
                  <Bar start={step.seq} end={step.seq} colour="bg-muted-foreground" />
                </div>
              ) : (
                <div key={`${step.start}`} className={`${GRID} border-t px-4 py-1.5 text-xs`}>
                  <span className="font-mono text-muted-foreground">
                    {step.start}-{step.end}
                  </span>
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-mono font-medium">{step.name}</span>
                    {step.lane > 0 ? (
                      <span className="hidden shrink-0 border px-1.5 text-[10px] text-muted-foreground sm:inline">
                        parallel
                      </span>
                    ) : null}
                  </span>
                  <span className="text-right font-mono tabular-nums">{step.ms} ms</span>
                  <Bar start={step.start} end={step.end} colour={LANE[step.lane]} />
                </div>
              ),
            )}
          </div>
        </div>
      </div>
      <figcaption className="border-t px-4 py-2 font-mono text-[11px] text-muted-foreground">
        The run page for a real recording of examples/async_support_agent.py
      </figcaption>
    </figure>
  );
}
