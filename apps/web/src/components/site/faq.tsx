/**
 * Straight answers, including what is not built yet. The README's status
 * table is the source for the last one.
 */

const QUESTIONS: { q: string; a: string }[] = [
  {
    q: "Does replay ever call my real tools?",
    a: "No. Every @tracer.tool is answered from the recording and its body never runs. A call that no recording matches raises UnmatchedToolCall inside the agent, so it cannot reach the real tool either. The demo counts real executions, and the count stays at 0 across all four replays.",
  },
  {
    q: "How do you handle LLM non-determinism?",
    a: "The recording fixes what the tools answer, so the only thing left to vary is the agent, which is the thing you are testing. Arguments are matched exactly first, then after a conservative normalisation: strings are trimmed, 2.0 equals 2, and keys set to None are dropped. Case is never folded. Reworded output text is a warning by default, not a failure.",
  },
  {
    q: "Can recording slow down or break my agent?",
    a: "Recording never raises into your code. Tool results and exceptions pass through unchanged, the run is buffered in memory and uploaded once when it ends, and a failed upload is logged and swallowed. Stop the API and run your agent: it finishes normally and reports uploaded: False. Without AGENTTRACE_PROJECT_ID the SDK never opens a socket.",
  },
  {
    q: "What does it take to add to an existing agent?",
    a: "Decorate the functions that are your tools with @tracer.tool and wrap the entry point in tracer.trace(...). Tools you cannot decorate go through tracer.record_tool_call. It works with any Python 3.12+ agent, sync or async, and the SDK has no runtime dependencies.",
  },
  {
    q: "How are parallel tool calls kept apart?",
    a: "Each call and its answer share a call_id. Sequence numbers give the order, but not which answer belongs to which call, so the explicit key is what lets two overlapping get_order calls be paired back up. The dashboard draws them as overlapping bars.",
  },
  {
    q: "Where does the data live?",
    a: "In your own PostgreSQL, behind the FastAPI service you run. A finished run is stored in one transaction, so a half-stored trace cannot exist, and a retried upload conflicts instead of creating a duplicate. Regression suites live in your repo as JSON recordings, and run-suite needs neither the API nor the network.",
  },
  {
    q: "What is not built yet?",
    a: "Semantic comparison, which would judge whether two differently worded answers mean the same thing. And auth and deployment: the SDK sends an API key that the API does not check yet, so run the API on a trusted network.",
  },
];

export function Faq() {
  return (
    <div className="divide-y rounded-md border bg-code">
      {QUESTIONS.map((item) => (
        <details key={item.q} className="group">
          <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 px-6 py-5 text-sm transition-colors group-open:text-signal hover:text-signal [&::-webkit-details-marker]:hidden">
            {item.q}
            <span
              aria-hidden
              className="text-lg leading-none text-muted-foreground transition-transform duration-200 group-open:rotate-45 group-open:text-signal"
            >
              +
            </span>
          </summary>
          <p className="max-w-3xl px-6 pb-6 text-[13px] leading-7 text-muted-foreground">{item.a}</p>
        </details>
      ))}
    </div>
  );
}
