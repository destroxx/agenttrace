"use client";

/**
 * The regressions AgentTrace catches, shown the way the product shows them:
 * the recorded run beside the replay, then the finding. Codes and severities
 * are the SDK defaults (`comparison.py`). Cases marked `replay_demo.py` are
 * that script's real output; cases marked `example` are illustrations of the
 * same support agent.
 */

import { useRef, useState, type KeyboardEvent } from "react";

import { Micro, Panel, VerdictChip } from "@/components/brand/primitives";

type Mark = "same" | "missing" | "new" | "changed";

interface Line {
  text: string;
  mark?: Mark;
}

interface Case {
  name: string;
  code: string;
  severity: "error" | "warning";
  source: string;
  recorded: Line[];
  replayed: Line[];
  finding: string;
}

const CASES: Case[] = [
  {
    name: "skipped step",
    code: "MISSING_TOOL_CALL",
    severity: "error",
    source: "replay_demo.py · v2",
    recorded: [
      { text: "07 get_delivery_status('A-1')" },
      { text: "09 get_delivery_status('B-2')" },
      { text: "11 format_reply('Dana', …)" },
    ],
    replayed: [
      { text: "get_delivery_status('A-1')", mark: "same" },
      { text: "not called", mark: "missing" },
      { text: "format_reply('Dana', …)", mark: "same" },
    ],
    finding: 'get_delivery_status(order_id="B-2") was recorded (seq 9) but never called. The reply was identical, so an output diff would have passed it.',
  },
  {
    name: "wrong arguments",
    code: "UNEXPECTED_TOOL_CALL",
    severity: "error",
    source: "replay_demo.py · v3",
    recorded: [
      { text: "03 get_order('A-1')" },
      { text: "04 get_order('B-2')" },
    ],
    replayed: [
      { text: "get_order('a-1')", mark: "new" },
      { text: "get_order('b-2')", mark: "new" },
    ],
    finding: 'get_order(order_id="a-1") matches no recorded call. It raised inside the agent instead of reaching the real tool, because normalisation never folds case.',
  },
  {
    name: "crashed run",
    code: "AGENT_ERROR",
    severity: "error",
    source: "replay_demo.py · v3",
    recorded: [
      { text: "status completed" },
      { text: "output: 'Hi Dana, …'" },
    ],
    replayed: [
      { text: "status failed", mark: "changed" },
      { text: "raised UnmatchedToolCall", mark: "new" },
    ],
    finding: "the agent raised UnmatchedToolCall, and the run status changed from 'completed' to 'failed'. Both are errors, alongside STATUS_CHANGED and OUTPUT_MISSING.",
  },
  {
    name: "broken output",
    code: "OUTPUT_STRUCTURE_CHANGED",
    severity: "error",
    source: "example",
    recorded: [
      { text: "output.message: '…'" },
      { text: "output.eta: 'tomorrow'" },
    ],
    replayed: [
      { text: "output.message: '…'", mark: "same" },
      { text: "key removed", mark: "missing" },
    ],
    finding: "a key added or removed, or a number changed, is a structural change and an error by default. Paths like generated_at can be ignored by policy.",
  },
  {
    name: "reordered calls",
    code: "TOOL_ORDER_CHANGED",
    severity: "warning",
    source: "example",
    recorded: [
      { text: "01 get_customer('c-42')" },
      { text: "03 get_order('A-1')" },
    ],
    replayed: [
      { text: "get_order('A-1')", mark: "changed" },
      { text: "get_customer('c-42')", mark: "changed" },
    ],
    finding: "the same calls in a different order. A warning by default; raise it to error for agents where order matters, or lower it to info where it never does.",
  },
  {
    name: "reworded reply",
    code: "OUTPUT_TEXT_CHANGED",
    severity: "warning",
    source: "replay_demo.py · v4",
    recorded: [{ text: "sign-off: 'Support'" }],
    replayed: [{ text: "sign-off: 'The support team'", mark: "changed" }],
    finding: "every call matched and only the wording changed, so the run passes with a warning. Exact text is brittle for language agents; one severity override makes it strict.",
  },
];

const MARK: Record<Mark, string> = {
  same: "text-foreground",
  missing: "text-fail italic",
  new: "text-fail",
  changed: "text-warn",
};

const MARK_LABEL: Record<Mark, string> = {
  same: "match",
  missing: "missing",
  new: "unexpected",
  changed: "changed",
};

export function RegressionExplorer() {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const item = CASES[active];
  const verdict = item.severity === "error" ? "fail" : "pass";

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const delta = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    const next = (active + delta + CASES.length) % CASES.length;
    setActive(next);
    tabs.current[next]?.focus();
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div role="tablist" aria-label="Regressions" aria-orientation="vertical" onKeyDown={onKeyDown} className="flex flex-col divide-y rounded-md border">
        {CASES.map((entry, index) => {
          const selected = index === active;
          return (
            <button
              key={entry.name}
              ref={(node) => {
                tabs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`reg-tab-${index}`}
              aria-selected={selected}
              aria-controls="reg-panel"
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(index)}
              className={`group relative grid min-h-16 cursor-pointer grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-4 px-5 py-4 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-signal ${
                selected ? "bg-card" : "hover:bg-card/60"
              }`}
            >
              <span
                aria-hidden
                className={`absolute inset-y-0 left-0 w-0.5 transition-colors ${selected ? "bg-signal" : "bg-transparent"}`}
              />
              <span className={`font-display text-lg font-extrabold tabular-nums ${selected ? "text-signal" : "text-muted-foreground"}`}>
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <span className="text-sm">{entry.name}</span>
                <span className="truncate text-[11px] text-muted-foreground">{entry.code}</span>
              </span>
              <span
                className={`size-2 rounded-full ${entry.severity === "error" ? "bg-fail" : "bg-warn"}`}
                title={entry.severity}
                aria-label={entry.severity}
              />
            </button>
          );
        })}
      </div>

      <div role="tabpanel" id="reg-panel" aria-labelledby={`reg-tab-${active}`}>
        <Panel className="flex h-full flex-col">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
            <span className="text-sm">{item.name}</span>
            <Micro>{item.source}</Micro>
          </div>
          <div className="grid flex-1 grid-cols-2 divide-x">
            <div className="flex flex-col gap-3 p-6">
              <Micro>recorded</Micro>
              {item.recorded.map((line) => (
                <p key={line.text} className="truncate text-[13px] text-muted-foreground">
                  {line.text}
                </p>
              ))}
            </div>
            <div className="flex flex-col gap-3 p-6">
              <Micro tone="brand">replayed</Micro>
              {item.replayed.map((line) => (
                <p key={line.text} className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className={`truncate ${MARK[line.mark ?? "same"]}`}>{line.text}</span>
                  <span className={`shrink-0 text-[10px] tracking-[0.12em] uppercase ${line.mark === "same" ? "text-pass" : MARK[line.mark ?? "same"].replace(" italic", "")}`}>
                    {MARK_LABEL[line.mark ?? "same"]}
                  </span>
                </p>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-3 border-t bg-background/40 px-6 py-5">
            <div className="flex flex-wrap items-center gap-3">
              <VerdictChip verdict={verdict} />
              <span className={`text-xs ${item.severity === "error" ? "text-fail" : "text-warn"}`}>
                {item.code} · {item.severity}
              </span>
            </div>
            <p className="text-[13px] leading-6 text-muted-foreground">{item.finding}</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
