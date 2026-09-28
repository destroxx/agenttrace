import type { Metadata } from "next";

import { DashboardPreview } from "@/components/site/dashboard-preview";
import { Faq } from "@/components/site/faq";
import { HeroVisual } from "@/components/site/hero-visual";
import {
  ButtonLink,
  C,
  D,
  Display,
  F,
  FAIL,
  K,
  Micro,
  Panel,
  PASS,
  RecChip,
  S,
  Section,
  Window,
} from "@/components/site/primitives";
import { RegressionExplorer } from "@/components/site/regression-explorer";
import { ReplayLab } from "@/components/site/replay-lab";

export const metadata: Metadata = {
  title: { absolute: "AgentTrace: regression tests for AI agents" },
};

/*
 * Every claim, code sample, finding and number on this page comes from the
 * SDK, the README or a real run of the examples, so it has to change when
 * they do. Nothing here fetches: the page renders without the API running.
 *
 * Copy rules: no em-dashes, no arrows on buttons.
 */

export default function HomePage() {
  return (
    <>
      <Hero />
      <Counter />
      <Regressions />
      <How />
      <Demo />
      <Dashboard />
      <Sdk />
      <Ci />
      <Quickstart />
      <Questions />
      <FinalCta />
    </>
  );
}

function Hero() {
  return (
    <section className="border-b">
      <div className="mx-auto grid w-full max-w-7xl items-center gap-16 px-5 py-20 sm:px-8 md:py-28 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="flex flex-col gap-8">
          <div className="animate-rise">
            <RecChip>rec · every tool call and its answer</RecChip>
          </div>
          <Display as="h1" className="animate-rise text-[2.75rem] [animation-delay:60ms] sm:text-6xl xl:text-7xl">
            Test every agent change against a real run.
          </Display>
          <p className="animate-rise max-w-xl text-sm leading-7 text-muted-foreground [animation-delay:120ms] md:text-[15px]">
            AgentTrace records a real run, every tool call and every answer. Replay the next
            prompt, model or code change against that recording without calling a single real
            tool, and get a PASS or FAIL you can gate a release on.
          </p>
          <div className="animate-rise flex flex-wrap gap-3 [animation-delay:180ms]">
            <ButtonLink href="#quickstart">Start recording</ButtonLink>
            <ButtonLink href="#demo" variant="secondary">
              Watch a replay
            </ButtonLink>
          </div>
        </div>
        <div className="animate-rise [animation-delay:240ms]">
          <HeroVisual />
        </div>
      </div>
    </section>
  );
}

/** Facts set as a tape counter: fixed-width, zero-padded readouts. */
function Counter() {
  const readouts = [
    { value: "000", label: "real tool calls during replay" },
    { value: "001", label: "request to store a whole run" },
    { value: "009", label: "finding codes, each with a severity" },
    { value: "000", label: "runtime dependencies in the SDK" },
  ];
  return (
    <section className="bg-band">
      <dl className="mx-auto grid w-full max-w-7xl grid-cols-2 lg:grid-cols-4">
        {readouts.map((item, index) => (
          <div
            key={item.label}
            className={`flex flex-col gap-3 px-5 py-10 sm:px-8 ${index % 2 ? "border-l" : ""} ${index > 1 ? "border-t lg:border-t-0" : ""} ${index === 2 ? "lg:border-l" : ""}`}
          >
            <dd className="font-display text-5xl leading-none font-black text-signal tabular-nums md:text-6xl">{item.value}</dd>
            <dt className="text-xs leading-5 text-muted-foreground">{item.label}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Regressions() {
  return (
    <Section
      id="regressions"
      index={1}
      label="regressions"
      title="Agents break quietly. AgentTrace shows you where."
      lead="Every difference between a recording and its replay becomes a finding with a stable code and a severity. These are the defaults, and a ComparisonPolicy can raise, lower or ignore any of them."
    >
      <RegressionExplorer />
    </Section>
  );
}

function How() {
  const steps = [
    {
      name: "Record",
      body: "Wrap the agent and decorate its tools. The SDK buffers the run in memory, snapshotting each value as it is recorded.",
      visual: (
        <>
          <C> 3</C> <F>get_order</F>(<S>&quot;A-1&quot;</S>){"\n"}
          <C> 4</C> <F>get_order</F>(<S>&quot;B-2&quot;</S>) <C>parallel</C>{"\n"}
          <C> 5</C> answer A-1 <C>50 ms</C>{"\n"}
          <C> 6</C> answer B-2 <C>50 ms</C>
        </>
      ),
    },
    {
      name: "Save",
      body: "The finished run is stored in one transaction, keyed by its own id. A retried upload conflicts instead of duplicating.",
      visual: (
        <>
          <F>POST</F> /runs/ingest{"\n"}
          <PASS>201</PASS> 14 events stored{"\n"}
          <F>POST</F> /runs/ingest <C>retry</C>{"\n"}
          <D>409</D> already stored
        </>
      ),
    },
    {
      name: "Replay",
      body: "Your unchanged entry point runs again. Every decorated tool answers from the recording and never executes.",
      visual: (
        <>
          <F>get_order</F>(<S>&quot;A-1&quot;</S>)  <PASS>exact</PASS>{"\n"}
          <F>get_order</F>(<S>&quot; B-2&quot;</S>) <D>normalized</D>{"\n"}
          <F>get_order</F>(<S>&quot;a-1&quot;</S>)  <FAIL>unmatched</FAIL>{"\n"}
          <C>real tool calls: 0</C>
        </>
      ),
    },
    {
      name: "Compare",
      body: "Skipped calls, unexpected calls, a changed status or a changed output shape each fail the run.",
      visual: (
        <>
          <FAIL /> 1 error, 0 warnings{"\n"}
          <FAIL>error</FAIL> MISSING_TOOL_CALL{"\n"}
          <C>get_delivery_status(</C>{"\n"}
          <C>  &quot;B-2&quot;) never called</C>
        </>
      ),
    },
  ];
  return (
    <Section
      id="how"
      index={2}
      label="how it works"
      title="Record once. Replay every change."
      lead="The recording becomes the fixture. Every future version of the agent is tested against what the tools actually returned, not against a mock someone wrote from memory."
      band
    >
      {/* A horizontal track: four steps joined by one line, like a timeline. */}
      <ol className="relative grid gap-10 md:grid-cols-2 xl:grid-cols-4 xl:gap-6">
        <span aria-hidden className="absolute top-[0.6rem] right-0 left-0 hidden h-px bg-line-strong xl:block" />
        {steps.map((step, index) => (
          <li key={step.name} className="relative flex flex-col gap-5">
            <span className="relative z-10 flex items-center gap-3">
              <span className="size-5 rounded-full border-2 border-signal bg-band" aria-hidden />
              <span className="font-display text-lg font-extrabold text-signal tabular-nums">0{index + 1}</span>
            </span>
            <h3 className="font-display text-3xl font-extrabold">{step.name}</h3>
            <p className="text-[13px] leading-6 text-muted-foreground">{step.body}</p>
            <pre className="mt-auto overflow-x-auto rounded-md border bg-code p-4 text-xs leading-6">{step.visual}</pre>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function Demo() {
  return (
    <Section
      id="demo"
      index={3}
      label="replay demo"
      title="Four changes. One recording. Four verdicts."
      lead="A support agent was recorded once. Four changed versions were then replayed against that recording. Pick one to see how each tool call matched and what the comparison decided."
    >
      <ReplayLab />
    </Section>
  );
}

function Dashboard() {
  const points = [
    { name: "Paired", body: "A call and its answer share a call_id, so each step is one row, even when parallel calls interleave." },
    { name: "Parallel", body: "Steps are drawn across the run's sequence range. Calls in flight together show as overlapping bars." },
    { name: "Verdicts", body: "Every replay links to its recording and to its comparison report, grouped by severity." },
  ];
  return (
    <Section
      id="dashboard"
      index={4}
      label="dashboard"
      title="Read a run like a timeline, not a log."
      lead="A read-only view of everything the SDK uploads: projects, runs with their verdicts, each run's timeline and its comparison report."
      band
    >
      <div className="grid items-start gap-12 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <DashboardPreview />
        <div className="flex flex-col gap-8">
          <dl className="flex flex-col gap-7">
            {points.map((point) => (
              <div key={point.name} className="flex gap-4">
                <span className="mt-1.5 size-2 shrink-0 rounded-full bg-signal" aria-hidden />
                <div className="flex flex-col gap-1.5">
                  <dt className="text-sm">{point.name}</dt>
                  <dd className="text-[13px] leading-6 text-muted-foreground">{point.body}</dd>
                </div>
              </div>
            ))}
          </dl>
          <div>
            <ButtonLink href="/projects" variant="secondary">
              Open the dashboard
            </ButtonLink>
          </div>
        </div>
      </div>
    </Section>
  );
}

function Sdk() {
  return (
    <Section
      id="sdk"
      index={5}
      label="python sdk"
      title="One decorator per tool. Nothing new in your dependency tree."
      lead="The SDK runs inside your agent's process, so it uses the standard library only. Recording never raises into your code: tool results and exceptions pass through unchanged, and a failed upload is logged, never thrown."
    >
      <div className="grid gap-5 lg:grid-cols-2">
        <Window title="agent.py">
          <K>from</K> agenttrace <K>import</K> AgentTracer{"\n"}
          {"\n"}
          tracer = AgentTracer()  <C># reads AGENTTRACE_*</C>{"\n"}
          {"\n"}
          <D>@tracer.tool</D>{"\n"}
          <K>async def</K> <F>get_order</F>(order_id: str) -&gt; dict:{"\n"}
          {"    "}<K>return</K> {"{"}<S>&quot;id&quot;</S>: order_id, <S>&quot;status&quot;</S>: <S>&quot;shipped&quot;</S>{"}"}{"\n"}
          {"\n"}
          <K>async def</K> <F>run_agent</F>(input):{"\n"}
          {"    "}<K>async with</K> tracer.trace({"\n"}
          {"        "}<S>&quot;support-agent&quot;</S>, input=input, agent_version=<S>&quot;v1.0.0&quot;</S>,{"\n"}
          {"    "}) <K>as</K> trace:{"\n"}
          {"        "}order = <K>await</K> get_order(<S>&quot;A-1&quot;</S>){"\n"}
          {"        "}trace.set_output({"{"}<S>&quot;message&quot;</S>: <S>f&quot;Your order is </S>{"{"}order[<S>&apos;status&apos;</S>]{"}"}<S>.&quot;</S>{"}"})
        </Window>
        <Window title="test_agent.py">
          <K>from</K> agenttrace <K>import</K> ComparisonPolicy, Recording{"\n"}
          {"\n"}
          recording = <K>await</K> Recording.from_api(run_id){"\n"}
          result, report = <K>await</K> tracer.replay_and_compare({"\n"}
          {"    "}recording,{"\n"}
          {"    "}run_agent,{"\n"}
          {"    "}agent_version=<S>&quot;v2.0.0&quot;</S>,{"\n"}
          {"    "}policy=ComparisonPolicy(ignore_paths=[<S>&quot;generated_at&quot;</S>]),{"\n"}
          ){"\n"}
          <F>print</F>(report.format()){"\n"}
          <K>assert</K> report.passed{"\n"}
          {"\n"}
          <C># FAIL  1 error, 0 warnings, 0 info</C>{"\n"}
          <C>#   error  MISSING_TOOL_CALL  get_delivery_status(</C>{"\n"}
          <C>#          order_id=&quot;B-2&quot;) was recorded (seq 9) but never called</C>
        </Window>
      </div>
    </Section>
  );
}

function Ci() {
  const exits = [
    { code: "0", tone: "text-pass", text: "Every case passed." },
    { code: "1", tone: "text-fail", text: "At least one case failed. Each failure's errors are listed under it." },
    { code: "2", tone: "text-warn", text: "The suite itself could not run." },
  ];
  return (
    <Section
      id="ci"
      index={6}
      label="regression suites"
      title="Recordings live in your repo. The exit code is the gate."
      lead="Export a stored run to JSON, review it for secrets, and commit it next to a suite.toml. run-suite replays every case offline, with no API, no network and no real tools. This repo's own GitHub Actions workflow runs run-suite on every pull request, so a regression turns the PR red."
      band
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Window title="examples/suites/support/suite.toml">
            name = <S>&quot;support&quot;</S>{"\n"}
            agent = <S>&quot;examples.async_support_agent:run_agent&quot;</S>{"\n"}
            {"\n"}
            <D>[[cases]]</D>{"\n"}
            name = <S>&quot;two-orders&quot;</S>{"\n"}
            recording = <S>&quot;recordings/two-orders.json&quot;</S>
          </Window>
          <Window title="terminal">
            <C>$</C> agenttrace run-suite examples/suites/support/suite.toml{"\n"}
            <PASS />  two-orders{"\n"}
            suite support: 1 passed, 0 failed{"\n"}
            {"\n"}
            <C>$</C> agenttrace export $RUN_ID -o recordings/refund.json{"\n"}
            <C># prints the [[cases]] entry to paste, and refuses to overwrite without --force</C>
          </Window>
        </div>
        <Panel className="flex flex-col">
          <p className="border-b px-7 py-5">
            <Micro>exit codes</Micro>
          </p>
          <ul className="flex flex-col divide-y">
            {exits.map((exit) => (
              <li key={exit.code} className="flex items-center gap-6 px-7 py-6">
                <span className={`font-display text-5xl leading-none font-black ${exit.tone}`}>{exit.code}</span>
                <span className="text-[13px] leading-6 text-muted-foreground">{exit.text}</span>
              </li>
            ))}
          </ul>
          <p className="mt-auto border-t px-7 py-5 text-xs leading-6 text-muted-foreground">
            Any CI runner that fails a job on a non-zero exit can use it as it is.
          </p>
        </Panel>
      </div>
    </Section>
  );
}

const REPO_URL = "https://github.com/destroxx/agenttrace";

function Quickstart() {
  // Each line is a command, or a note (starting with "#") shown as a comment.
  // Mirrors README.md's Quickstart, shortened; the README stays the source.
  const steps = [
    {
      title: "Start Postgres",
      lines: [
        "cp .env.example .env",
        "# set POSTGRES_PASSWORD in .env, e.g. openssl rand -hex 16",
        "docker compose up -d",
        "# wait until docker compose ps shows (healthy)",
      ],
    },
    {
      title: "Configure, migrate and run the API",
      lines: [
        "cp apps/api/.env.example apps/api/.env",
        "# set the same POSTGRES_PASSWORD in apps/api/.env",
        "python3.12 -m venv .venv && source .venv/bin/activate",
        'pip install -e "apps/api[dev]" -e "packages/python-sdk[dev]"',
        "cd apps/api && alembic upgrade head && uvicorn app.main:app --reload",
      ],
    },
    {
      title: "Create a project, then record and replay",
      lines: [
        "# in a second shell, from the repo root",
        "source .venv/bin/activate",
        "export AGENTTRACE_PROJECT_ID=$(curl -s -X POST localhost:8000/api/v1/projects \\",
        "  -H 'content-type: application/json' -d '{\"name\":\"Demo\"}' \\",
        "  | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"id\"])')",
        "python examples/async_support_agent.py",
        "python examples/replay_demo.py",
      ],
    },
    {
      title: "Open the dashboard",
      lines: [
        "cd apps/web && cp .env.example .env.local",
        "npm install && npm run dev",
        "# then open http://localhost:3000/projects",
      ],
    },
  ];
  return (
    <Section
      id="quickstart"
      index={7}
      label="quickstart"
      title="Your first recording, replayed and judged."
      lead="You need Python 3.12+, Node 20+ and Docker. The demo agent is scripted, so there is no LLM and no API key. With AGENTTRACE_PROJECT_ID set, the two examples fill that project with a recording, its replays and their comparison reports."
    >
      <ol className="grid gap-5 md:grid-cols-2">
        {steps.map((step, index) => (
          <li key={step.title} className="flex min-w-0 flex-col gap-4 rounded-md border bg-card/50 p-6">
            <p className="flex items-baseline gap-4">
              <span className="font-display text-2xl font-black text-signal tabular-nums">0{index + 1}</span>
              <span className="text-sm">{step.title}</span>
            </p>
            <pre className="overflow-x-auto rounded-md border bg-code p-4 text-xs leading-6">
              {step.lines.map((line) =>
                line.startsWith("#") ? (
                  <C key={line}>
                    {line}
                    {"\n"}
                  </C>
                ) : (
                  <span key={line}>
                    {line.startsWith("  ") ? null : <C>$ </C>}
                    {line}
                    {"\n"}
                  </span>
                ),
              )}
            </pre>
          </li>
        ))}
      </ol>
      <p className="text-sm text-muted-foreground">
        <a
          href={`${REPO_URL}#quickstart`}
          className="text-foreground underline decoration-signal underline-offset-4 hover:text-signal"
        >
          Full setup in the README
        </a>
        , including troubleshooting and a DATABASE_URL alternative.
      </p>
    </Section>
  );
}

function Questions() {
  return (
    <Section id="faq" index={8} label="faq" title="Questions teams ask first." band>
      <Faq />
    </Section>
  );
}

function FinalCta() {
  return (
    <section className="border-t">
      <div className="mx-auto grid w-full max-w-7xl gap-10 px-5 py-28 sm:px-8 md:py-36 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-end">
        <div className="flex flex-col gap-8">
          <RecChip>untested</RecChip>
          <Display className="text-4xl md:text-6xl">Every prompt change is a deploy nobody tested.</Display>
        </div>
        <div className="flex flex-col gap-6">
          <p className="text-sm leading-7 text-muted-foreground md:text-[15px]">
            Record today&apos;s runs, and tomorrow&apos;s agent has something to be measured against.
            It takes a decorator on each tool and one context manager around the run.
          </p>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href="#quickstart">Start recording</ButtonLink>
            <ButtonLink href="/projects" variant="secondary">
              Open the dashboard
            </ButtonLink>
          </div>
        </div>
      </div>
    </section>
  );
}
