"use client";

/**
 * The hero's tape deck: the recorded support-agent run as a strip of spans,
 * with a playhead sweeping across while the v2 replay from
 * `examples/replay_demo.py` lands call by call, then its verdict. Real
 * sequence numbers, arguments and finding; the pacing is for show.
 */

import { useEffect, useState } from "react";

import { Micro, Panel, RecChip } from "@/components/site/primitives";

const LINES = [
  { seq: 1, end: 2, tool: "get_customer", args: "c-42", ok: true, lane: 0 },
  { seq: 3, end: 5, tool: "get_order", args: "A-1", ok: true, lane: 0 },
  { seq: 4, end: 6, tool: "get_order", args: "B-2", ok: true, lane: 1 },
  { seq: 7, end: 8, tool: "get_delivery_status", args: "A-1", ok: true, lane: 0 },
  { seq: 9, end: 10, tool: "get_delivery_status", args: "B-2", ok: false, lane: 0 },
  { seq: 11, end: 12, tool: "format_reply", args: "Dana", ok: true, lane: 0 },
] as const;

const LAST = 13;
const STEPS = LINES.length + 2; // every call, the verdict, then a pause

export function HeroVisual() {
  const [shown, setShown] = useState(STEPS);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setShown((n) => (n >= STEPS + 2 ? 0 : n + 1)), 700);
    return () => window.clearInterval(timer);
  }, []);

  const verdict = shown > LINES.length;
  const head = verdict ? 100 : shown === 0 ? 0 : (LINES[Math.min(shown, LINES.length) - 1].end / LAST) * 100;

  return (
    <figure className="flex flex-col gap-4">
      <Panel>
        <div className="flex items-center justify-between gap-3 border-b px-5 py-3">
          <RecChip tone="pass">replaying</RecChip>
          <span className="text-[11px] text-muted-foreground">support-agent · v2.0.0</span>
        </div>

        {/* The recording as a tape: one bar per call, the playhead on top. */}
        <div className="relative border-b px-5 py-4" aria-hidden>
          <div className="relative h-8">
            {LINES.map((line) => (
              <span
                key={line.seq}
                className={`absolute h-2.5 rounded-full ${line.ok ? "bg-foreground/35" : "bg-fail/70"}`}
                style={{
                  left: `${(line.seq / LAST) * 100}%`,
                  width: `${((line.end - line.seq) / LAST) * 100}%`,
                  top: line.lane ? "1.25rem" : "0.25rem",
                }}
              />
            ))}
            <span
              className="absolute -top-1 bottom-[-0.25rem] w-px bg-signal transition-[left] duration-500 ease-out"
              style={{ left: `${head}%` }}
            >
              <span className="absolute -top-1 -left-[3px] size-[7px] rounded-full bg-signal" />
            </span>
          </div>
        </div>

        <ol className="flex min-h-[14rem] flex-col gap-1 px-5 py-4 text-[12.5px] leading-6" aria-label="Replayed tool calls">
          {LINES.map((line, index) => (
            <li
              key={line.seq}
              className={`grid grid-cols-[1.75rem_minmax(0,1fr)_auto] gap-3 transition-opacity duration-300 ${
                index < shown ? "opacity-100" : "opacity-0"
              }`}
            >
              <span className="text-muted-foreground/60 tabular-nums">{String(line.seq).padStart(2, "0")}</span>
              <span className={`truncate ${line.ok ? "" : "text-muted-foreground line-through decoration-fail"}`}>
                {line.tool}
                <span className="text-muted-foreground">(&quot;{line.args}&quot;)</span>
              </span>
              <span className={line.ok ? "text-pass" : "text-fail"}>{line.ok ? "exact" : "not called"}</span>
            </li>
          ))}
        </ol>

        <div className={`flex flex-col gap-1.5 border-t px-5 py-4 transition-opacity duration-300 ${verdict ? "opacity-100" : "opacity-0"}`}>
          <Micro tone="fail">fail · missing_tool_call</Micro>
          <span className="text-xs text-muted-foreground">get_delivery_status(&quot;B-2&quot;) recorded at seq 9, never called</span>
        </div>
      </Panel>
      <figcaption className="text-center text-xs text-muted-foreground">
        every tool call answered from the recording · real tool calls: <span className="text-pass">0</span>
      </figcaption>
    </figure>
  );
}
