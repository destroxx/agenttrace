/**
 * A real pull request, drawn in HTML like `dashboard-preview.tsx`: PR #1 on
 * destroxx/agenttrace, which changed one line of the example agent to see
 * whether CI would notice. Title, diff, check results and the finding are
 * copied from that PR and its CI run (actions run 36480253178); the PR was
 * closed without merging. If the workflow's job names change, this goes
 * stale: update it from `gh pr checks 1`.
 */

export const PR_URL = "https://github.com/destroxx/agenttrace/pull/1";

// The PR's own title, quoted exactly as GitHub shows it.
const TITLE = "Demo: deliberate regression — do not merge";

// Why three jobs fail for one regression: the Regression suite job runs
// `agenttrace run-suite` on the example suite directly, and both SDK jobs
// run the SDK's tests, where `test_the_example_suite_passes_end_to_end`
// (packages/python-sdk/tests/test_cli.py) runs the same example suite and
// asserts it passes. The API and Web jobs never run the agent, so they pass.
const CHECKS: { name: string; ok: boolean }[] = [
  { name: "Regression suite", ok: false },
  { name: "SDK (Python 3.12)", ok: false },
  { name: "SDK (Python 3.13)", ok: false },
  { name: "API", ok: true },
  { name: "Web", ok: true },
];

export function PrProof() {
  return (
    <figure className="overflow-hidden rounded-md border bg-code">
      <div className="flex items-center gap-3 border-b bg-card px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
        </span>
        <span className="flex-1 truncate rounded-sm border bg-background px-3 py-1 text-[11px] text-muted-foreground">
          github.com/destroxx/agenttrace/pull/1
        </span>
      </div>

      <div className="flex flex-col gap-2 border-b px-5 py-5 sm:px-6">
        <p className="text-base text-foreground">
          {TITLE} <span className="text-muted-foreground">#1</span>
        </p>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="rounded-sm bg-muted px-2 py-0.5">closed, never merged</span>
          <span>demo/regression</span>
          <span>1 file changed, +1 −1</span>
        </p>
      </div>

      <div className="grid md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:divide-x">
        <div className="flex min-w-0 flex-col gap-3 border-b p-5 sm:p-6 md:border-b-0">
          <span className="text-[11px] tracking-[0.18em] text-muted-foreground uppercase">examples/async_support_agent.py</span>
          <pre className="overflow-x-auto rounded-sm border bg-background/60 text-[12px] leading-6">
            <span className="block bg-fail/10 px-3 text-fail">
              - orders = await asyncio.gather(*(get_order(order_id) for order_id in order_ids))
            </span>
            <span className="block bg-pass/10 px-3 text-pass">
              + orders = await asyncio.gather(*(get_order(order_id) for order_id in order_ids[:1]))
            </span>
          </pre>
          <span className="text-xs text-muted-foreground">
            The agent now looks up only the first order it was asked about.
          </span>
        </div>

        <div className="flex flex-col p-5 sm:p-6">
          <span className="mb-3 text-[11px] tracking-[0.18em] text-muted-foreground uppercase">checks</span>
          <ul className="flex flex-col divide-y">
            {CHECKS.map((check) => (
              <li key={check.name} className="flex items-center justify-between gap-3 py-2 text-[13px]">
                <span className="flex items-center gap-2.5">
                  <span className={`size-2 rounded-full ${check.ok ? "bg-pass" : "bg-fail"}`} aria-hidden />
                  {check.name}
                </span>
                <span className={`text-xs ${check.ok ? "text-pass" : "text-fail"}`}>{check.ok ? "passing" : "failing"}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex flex-col gap-2 border-t bg-fail/5 px-5 py-4 text-[12.5px] sm:px-6">
        <span className="text-muted-foreground">
          Regression suite · run-suite · <span className="text-fail">FAIL two-orders, 7 errors</span>, including
        </span>
        <span className="leading-6">
          <span className="text-fail">MISSING_TOOL_CALL</span>{" "}
          <span className="text-foreground">get_order(order_id=&quot;B-2&quot;) was recorded (seq 4) but never called</span>
        </span>
      </div>
    </figure>
  );
}
