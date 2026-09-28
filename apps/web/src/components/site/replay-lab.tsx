"use client";

/**
 * The four agent versions from `examples/replay_demo.py`, replayed against one
 * recording. Every row, finding and count below is that script's real output
 * (run offline, 2026-09-29, lightly condensed); if the demo or the comparison engine changes,
 * re-run it and update this data rather than editing it by hand.
 */

import { useRef, useState, type KeyboardEvent } from "react";

type Outcome = "exact" | "normalized" | "unmatched" | "unused";

interface Row {
  tool: string;
  recorded: string | null;
  replayed: string | null;
  outcome: Outcome;
}

interface Version {
  id: string;
  label: string;
  change: string;
  verdict: "pass" | "fail";
  summary: string;
  rows: Row[];
  findings: { severity: "error" | "warning"; code: string; message: string }[];
  moreFindings?: number;
  takeaway: string;
}

const REPLY = "customer_name='Dana', lines=[…]";
const MATCHED: Row[] = [
  { tool: "get_customer", recorded: "customer_id='c-42'", replayed: "customer_id='c-42'", outcome: "exact" },
  { tool: "get_order", recorded: "order_id='A-1'", replayed: "order_id='A-1'", outcome: "exact" },
  { tool: "get_order", recorded: "order_id='B-2'", replayed: "order_id='B-2'", outcome: "exact" },
  { tool: "get_delivery_status", recorded: "order_id='A-1'", replayed: "order_id='A-1'", outcome: "exact" },
  { tool: "get_delivery_status", recorded: "order_id='B-2'", replayed: "order_id='B-2'", outcome: "exact" },
  { tool: "format_reply", recorded: REPLY, replayed: REPLY, outcome: "exact" },
];

const VERSIONS: Version[] = [
  {
    id: "v1",
    label: "v1 · unchanged",
    change: "None. This is the exact code that was recorded.",
    verdict: "pass",
    summary: "6 exact · 0 unmatched · 0 unused · output same as recording",
    rows: MATCHED,
    findings: [],
    takeaway: "Same code, same answers. The baseline every other version is judged against.",
  },
  {
    id: "v2",
    label: "v2 · skips a lookup",
    change: "Skips the delivery lookup for orders that are still processing, because it thinks it already knows.",
    verdict: "fail",
    summary: "5 exact · 0 unmatched · 1 unused · output same as recording",
    rows: MATCHED.map((row, index) =>
      index === 4 ? { ...row, replayed: null, outcome: "unused" } : row,
    ),
    findings: [
      {
        severity: "error",
        code: "MISSING_TOOL_CALL",
        message: 'get_delivery_status(order_id="B-2") was recorded (seq 9) but never called',
      },
    ],
    takeaway:
      "The reply came out identical, so an output diff would have passed it. The skipped call is what fails it.",
  },
  {
    id: "v3",
    label: "v3 · lowercases ids",
    change: "Looks orders up as “a-1” instead of “A-1”.",
    verdict: "fail",
    summary: "1 exact · 2 unmatched · 5 unused · status failed",
    rows: [
      MATCHED[0],
      { tool: "get_order", recorded: null, replayed: "order_id='a-1'", outcome: "unmatched" },
      { tool: "get_order", recorded: null, replayed: "order_id='b-2'", outcome: "unmatched" },
      { ...MATCHED[1], replayed: null, outcome: "unused" },
      { ...MATCHED[2], replayed: null, outcome: "unused" },
      { ...MATCHED[3], replayed: null, outcome: "unused" },
      { ...MATCHED[4], replayed: null, outcome: "unused" },
      { ...MATCHED[5], replayed: null, outcome: "unused" },
    ],
    findings: [
      {
        severity: "error",
        code: "AGENT_ERROR",
        message: "the agent raised UnmatchedToolCall: no unused recorded call to 'get_order' matches arguments {'order_id': 'a-1'}",
      },
      { severity: "error", code: "STATUS_CHANGED", message: "run status changed from 'completed' to 'failed'" },
      { severity: "error", code: "UNEXPECTED_TOOL_CALL", message: 'get_order(order_id="a-1") matches no recorded call' },
      { severity: "error", code: "OUTPUT_MISSING", message: "the replay has no output" },
    ],
    moreFindings: 6,
    takeaway:
      "Normalisation never folds case, because “A-1” and “a-1” can be different orders. The unmatched call raised inside the agent instead of reaching the real tool.",
  },
  {
    id: "v4",
    label: "v4 · rewords reply",
    change: "Signs off as “The support team” instead of “Support”.",
    verdict: "pass",
    summary: "6 exact · 0 unmatched · 0 unused · output text differs",
    rows: MATCHED,
    findings: [
      {
        severity: "warning",
        code: "OUTPUT_TEXT_CHANGED",
        message: 'output.message text changed: the sign-off "Support" became "The support team"',
      },
    ],
    takeaway:
      "Rewording is a warning, not a failure, because exact text equality is brittle for language agents. One severity override makes it strict.",
  },
];

const OUTCOME_STYLE: Record<Outcome, string> = {
  exact: "text-pass",
  normalized: "text-warn",
  unmatched: "text-fail",
  unused: "text-fail",
};

export function ReplayLab() {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const version = VERSIONS[active];

  // Roving focus for the tab list, per the WAI-ARIA tabs pattern.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const delta = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    const target =
      event.key === "Home" ? 0 : event.key === "End" ? VERSIONS.length - 1 : delta !== undefined
        ? (active + delta + VERSIONS.length) % VERSIONS.length
        : null;
    if (target === null) return;
    event.preventDefault();
    setActive(target);
    tabs.current[target]?.focus();
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <div
        role="tablist"
        aria-label="Agent versions"
        aria-orientation="vertical"
        onKeyDown={onKeyDown}
        className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0"
      >
        {VERSIONS.map((item, index) => {
          const selected = index === active;
          return (
            <button
              key={item.id}
              ref={(node) => {
                tabs.current[index] = node;
              }}
              role="tab"
              id={`lab-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`lab-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(index)}
              className={`flex min-h-12 shrink-0 cursor-pointer items-center justify-between gap-3 border px-4 py-3 text-left text-[13px] transition-colors rounded-md focus-visible:outline-2 focus-visible:outline-signal lg:shrink ${
                selected ? "border-signal bg-code text-foreground" : "border-border text-muted-foreground hover:border-line-strong hover:text-foreground"
              }`}
            >
              <span className="whitespace-nowrap">{item.label}</span>
              <span
                className={`rounded-sm px-1.5 py-0.5 text-[10px] tracking-[0.12em] ${
                  item.verdict === "pass" ? "bg-pass/12 text-pass" : "bg-fail/12 text-fail"
                }`}
              >
                {item.verdict.toUpperCase()}
              </span>
            </button>
          );
        })}
        <p className="hidden px-4 pt-3 font-mono text-xs leading-5 text-muted-foreground lg:block">
          real tool executions during all 4 replays: <span className="text-pass">0</span>
        </p>
      </div>

      <div
        role="tabpanel"
        id={`lab-panel-${version.id}`}
        aria-labelledby={`lab-tab-${version.id}`}
        className="min-w-0 overflow-hidden rounded-md border bg-code"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
          <p className="text-[13px]">
            <span className="text-[11px] tracking-[0.18em] text-signal uppercase">change </span>
            {version.change}
          </p>
          <span className="font-mono text-xs text-muted-foreground">{version.summary}</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] font-mono text-xs">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b">
                <th scope="col" className="px-5 py-2 font-normal">tool</th>
                <th scope="col" className="px-3 py-2 font-normal">recorded</th>
                <th scope="col" className="px-3 py-2 font-normal">new agent</th>
                <th scope="col" className="px-5 py-2 text-right font-normal">outcome</th>
              </tr>
            </thead>
            <tbody>
              {version.rows.map((row, index) => (
                <tr key={`${version.id}-${index}`} className="animate-rise border-b border-border/50 last:border-0" style={{ animationDelay: `${index * 35}ms` }}>
                  <td className="px-5 py-2 text-syntax-function">{row.tool}</td>
                  <td className="px-3 py-2 text-muted-foreground">{row.recorded ?? <span className="italic opacity-70">no recording</span>}</td>
                  <td className="px-3 py-2">{row.replayed ?? <span className="italic text-muted-foreground opacity-70">not called</span>}</td>
                  <td className={`px-5 py-2 text-right ${OUTCOME_STYLE[row.outcome]}`}>{row.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-2 border-t px-5 py-4 font-mono text-xs">
          <p className="text-sm">
            <span className={`font-semibold ${version.verdict === "pass" ? "text-pass" : "text-fail"}`}>
              {version.verdict.toUpperCase()}
            </span>{" "}
            <span className="text-muted-foreground">
              {version.findings.filter((f) => f.severity === "error").length + (version.moreFindings ?? 0)} errors,{" "}
              {version.findings.filter((f) => f.severity === "warning").length} warnings
            </span>
          </p>
          {version.findings.map((finding) => (
            <p key={finding.code + finding.message} className="flex gap-3">
              <span className={`w-14 shrink-0 ${finding.severity === "error" ? "text-fail" : "text-warn"}`}>
                {finding.severity}
              </span>
              <span className="shrink-0 text-warn">{finding.code}</span>
              <span className="min-w-0 truncate text-muted-foreground" title={finding.message}>
                {finding.message}
              </span>
            </p>
          ))}
          {version.moreFindings ? (
            <p className="text-muted-foreground">
              … and {version.moreFindings} more (MISSING_TOOL_CALL ×5, UNEXPECTED_TOOL_CALL ×1)
            </p>
          ) : null}
          {version.findings.length === 0 ? (
            <p className="text-muted-foreground">No findings. Calls, order, status and output all matched.</p>
          ) : null}
        </div>

        <p className="border-t border-dashed px-5 py-4 text-[13px] leading-6 text-muted-foreground">
          <span className="text-[11px] tracking-[0.18em] text-signal uppercase">why it matters </span>
          {version.takeaway}
        </p>
      </div>
    </div>
  );
}
