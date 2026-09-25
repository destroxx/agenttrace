import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { SeverityBadge, VerdictBadge } from "@/components/badges";
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
    { label: "Projects", href: "/" },
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
    <section className="flex flex-col gap-2 rounded-lg border border-dashed p-6 text-sm">
      <h2 className="text-base font-semibold">This run has no comparison report</h2>
      <p className="text-muted-foreground">
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

function Report({ comparison }: { comparison: Comparison }) {
  const { report, verdict } = comparison;
  const findings = report.findings ?? [];
  const bySeverity = report.counts?.by_severity ?? {};
  const byCode = Object.entries(report.counts?.by_code ?? {});
  const passed = verdict === "pass";

  return (
    <>
      <section
        className={`flex flex-col gap-2 rounded-lg border p-5 ${
          passed
            ? "border-emerald-500/40 bg-emerald-500/10"
            : "border-destructive/40 bg-destructive/10"
        }`}
      >
        <div className="flex items-center gap-3">
          <VerdictBadge verdict={verdict} className="h-6 px-3 text-sm" />
          <span className="text-base font-medium">
            {passed
              ? "The replay behaved like its recording."
              : "The replay differs from its recording in ways that fail the policy."}
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Replay{" "}
          <Link href={`/runs/${comparison.replay_run_id}`} className="font-mono underline underline-offset-4">
            {shortId(comparison.replay_run_id)}
          </Link>{" "}
          compared with recording{" "}
          <Link href={`/runs/${comparison.recording_run_id}`} className="font-mono underline underline-offset-4">
            {shortId(comparison.recording_run_id)}
          </Link>{" "}
          · uploaded {formatTimestamp(comparison.created_at)}
        </p>
      </section>

      <section className="flex flex-wrap gap-3">
        {SEVERITIES.map((severity) => (
          <div key={severity} className="flex min-w-28 flex-col gap-1 rounded-lg border px-4 py-3">
            <span className="text-xs text-muted-foreground">{severity}</span>
            <span className="text-2xl font-semibold tabular-nums">{bySeverity[severity] ?? 0}</span>
          </div>
        ))}
        {byCode.length > 0 ? (
          <dl className="flex flex-col justify-center gap-0.5 rounded-lg border px-4 py-3 text-xs">
            {byCode.map(([code, count]) => (
              <div key={code} className="flex gap-3">
                <dt className="font-mono">{code}</dt>
                <dd className="ml-auto tabular-nums">{count}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Findings</h2>
        {findings.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No findings: the tool calls, their order, the status and the output all matched.
          </p>
        ) : (
          <ol className="flex flex-col overflow-hidden rounded-lg border">
            {findings.map((finding, index) => (
              <li key={index} className="border-t first:border-t-0">
                <details className="group">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 px-4 py-2.5 text-sm hover:bg-muted/30 [&::-webkit-details-marker]:hidden">
                    <span className="inline-block w-3 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden>
                      ›
                    </span>
                    <SeverityBadge severity={finding.severity} />
                    <code className="text-xs font-medium">{finding.code}</code>
                    <span className="min-w-0 flex-1 break-words">{finding.message}</span>
                  </summary>
                  <div className="border-t bg-muted/10 px-4 py-3">
                    <JsonBlock value={finding.details} className="rounded-md border" />
                  </div>
                </details>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
