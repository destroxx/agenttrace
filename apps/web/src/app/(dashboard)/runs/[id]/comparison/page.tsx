import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { SeverityBadge, VerdictBadge } from "@/components/badges";
import { Micro, Panel, Timecode } from "@/components/brand/primitives";
import { JsonBlock } from "@/components/json-view";
import { PageHeader, type Crumb } from "@/components/page-header";
import { getComparison, getProject, getRun, isUuid, SEVERITIES, type Comparison } from "@/lib/api";
import { formatTimestamp, shortId } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ComparisonPage({
  params,
}: PageProps<"/runs/[id]/comparison">) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }

  const [run, comparison] = await Promise.all([getRun(id), getComparison(id)]);
  if (!run.ok && run.kind === "not_found") {
    notFound();
  }
  if (!run.ok) {
    return <ApiProblem failure={run} />;
  }
  const project = await getProject(run.data.project_id);
  const crumbs: Crumb[] = [
    { label: "Projects", href: "/projects" },
    {
      label: project.ok ? project.data.name : "Project",
      href: `/projects/${run.data.project_id}`,
    },
    { label: `${run.data.agent_name} ${shortId(id)}`, href: `/runs/${id}` },
  ];

  if (!comparison.ok) {
    return (
      <>
        <PageHeader crumbs={crumbs} title="Comparison report" />
        {comparison.kind === "not_found" ? (
          <NoReport isReplay={run.data.replay_of_run_id !== null} />
        ) : (
          <ApiProblem failure={comparison} />
        )}
      </>
    );
  }

  return (
    <>
      <PageHeader crumbs={crumbs} title="Comparison report" />
      <Report comparison={comparison.data} />
    </>
  );
}

function NoReport({ isReplay }: { isReplay: boolean }) {
  return (
    <section className="bg-grid flex flex-col gap-3 rounded-md border border-dashed border-line-strong p-6 text-[13px] leading-6 sm:p-8">
      <Micro tone="brand">no report</Micro>
      <h2 className="font-display text-2xl font-extrabold tracking-[-0.03em]">This run has no comparison report</h2>
      <p className="max-w-3xl text-muted-foreground">
        {isReplay
          ? "It is a replay, but no report was uploaded for it."
          : "It is not a replay, so there is nothing it was compared against."}{" "}
        Reports are produced by the SDK, not the dashboard: after{" "}
        <code>tracer.replay_and_compare(recording, agent_fn)</code> the report is uploaded
        next to the replay run whenever <code>AGENTTRACE_PROJECT_ID</code> is set (unless
        called with <code>upload_report=False</code>). A report can also be sent explicitly
        with <code>tracer.upload_comparison(report)</code>.
      </p>
    </section>
  );
}

const LINK = "underline decoration-line-strong underline-offset-4 hover:text-signal hover:decoration-signal";

const SEVERITY_TONE: Record<string, string> = {
  error: "text-fail",
  warning: "text-warn",
  info: "text-foreground",
};

function Report({ comparison }: { comparison: Comparison }) {
  const { report, verdict } = comparison;
  const findings = report.findings ?? [];
  const bySeverity = report.counts?.by_severity ?? {};
  const byCode = Object.entries(report.counts?.by_code ?? {});
  const passed = verdict === "pass";

  return (
    <>
      <section
        className={`flex flex-col gap-4 rounded-md border border-l-4 bg-code p-5 sm:p-6 ${
          passed ? "border-pass/40 border-l-pass" : "border-fail/40 border-l-fail"
        }`}
      >
        <div className="flex flex-wrap items-center gap-4">
          <VerdictBadge verdict={verdict} className="h-7 px-3 text-xs" />
          <span className="text-[15px] leading-7">
            {passed
              ? "The replay behaved like its recording."
              : "The replay differs from its recording in ways that fail the policy."}
          </span>
        </div>
        <p className="text-[13px] leading-6 text-muted-foreground">
          Replay{" "}
          <Link href={`/runs/${comparison.replay_run_id}`} className={LINK}>
            {shortId(comparison.replay_run_id)}
          </Link>{" "}
          compared with recording{" "}
          <Link href={`/runs/${comparison.recording_run_id}`} className={LINK}>
            {shortId(comparison.recording_run_id)}
          </Link>{" "}
          · uploaded {formatTimestamp(comparison.created_at)}
        </p>
      </section>

      <section className="flex flex-col gap-5">
        <Timecode as="h2" index={1} label="counts" />
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.5fr)]">
          {SEVERITIES.map((severity) => {
            const count = bySeverity[severity] ?? 0;
            return (
              <Panel key={severity}>
                <div className="flex flex-col gap-2 px-4 py-4">
                  <Micro>{severity}</Micro>
                  <span
                    className={`font-display text-5xl leading-none font-extrabold tabular-nums ${
                      count === 0 ? "text-muted-foreground" : SEVERITY_TONE[severity]
                    }`}
                  >
                    <span aria-hidden>{String(count).padStart(3, "0")}</span>
                    <span className="sr-only">{count}</span>
                  </span>
                </div>
              </Panel>
            );
          })}
          {byCode.length > 0 ? (
            <Panel className="sm:col-span-3 lg:col-span-1">
              <dl className="flex flex-col gap-1.5 px-4 py-4 text-xs">
                {byCode.map(([code, count]) => (
                  <div key={code} className="flex gap-3">
                    <dt className="min-w-0 break-all">{code}</dt>
                    <dd className="ml-auto tabular-nums">{count}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          ) : null}
        </div>
      </section>

      <section className="flex flex-col gap-5">
        <Timecode as="h2" index={2} label="findings" />
        {findings.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            No findings: the tool calls, their order, the status and the output all matched.
          </p>
        ) : (
          <Panel>
            <ol className="flex flex-col">
              {findings.map((finding, index) => (
                <li key={index} className="border-t first:border-t-0">
                  <details className="group">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 px-4 py-3 text-[13px] transition-colors hover:bg-card [&::-webkit-details-marker]:hidden">
                      <span className="inline-block w-3 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden>
                        ›
                      </span>
                      <SeverityBadge severity={finding.severity} />
                      <code className="text-xs font-medium">{finding.code}</code>
                      <span className="min-w-0 flex-1 break-words">{finding.message}</span>
                    </summary>
                    <div className="border-t bg-background/60 px-4 py-4">
                      <JsonBlock value={finding.details} className="rounded-md border" />
                    </div>
                  </details>
                </li>
              ))}
            </ol>
          </Panel>
        )}
      </section>
    </>
  );
}
