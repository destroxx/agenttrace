import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { ReplayBadge, StatusBadge, VerdictBadge } from "@/components/badges";
import { Panel, Timecode } from "@/components/brand/primitives";
import { JsonView } from "@/components/json-view";
import { PageHeader, type Crumb } from "@/components/page-header";
import { RunTimeline } from "@/components/timeline";
import { getComparison, getProject, getRun, isUuid, listEvents } from "@/lib/api";
import { durationBetween, formatDuration, formatTimestamp, shortId } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }

  const [run, events, comparison] = await Promise.all([
    getRun(id),
    listEvents(id),
    getComparison(id),
  ]);
  if (!run.ok && run.kind === "not_found") {
    notFound();
  }
  if (!run.ok) {
    return <ApiProblem failure={run} />;
  }
  // Only for the breadcrumb; the page is still useful without it.
  const project = await getProject(run.data.project_id);

  const crumbs: Crumb[] = [
    { label: "Projects", href: "/projects" },
    {
      label: project.ok ? project.data.name : "Project",
      href: `/projects/${run.data.project_id}`,
    },
  ];
  const r = run.data;

  return (
    <>
      <PageHeader crumbs={crumbs} title={r.agent_name}>
        <StatusBadge status={r.status} />
        {r.agent_version ? (
          <span className="inline-flex h-5 items-center rounded-sm border border-line-strong px-2 text-xs">{r.agent_version}</span>
        ) : null}
        {r.replay_of_run_id ? <ReplayBadge /> : null}
        {comparison.ok ? (
          <Link href={`/runs/${r.id}/comparison`} title="Open the comparison report" className="inline-flex rounded-sm">
            <VerdictBadge verdict={comparison.data.verdict} />
          </Link>
        ) : null}
      </PageHeader>

      <Panel>
        {/* Each fact draws its bottom and right hairlines; the negative margins tuck the outer ones under the panel's border. */}
        <dl className="-mr-px -mb-px grid grid-cols-1 text-[13px] sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Run">
            <span className="text-xs">{r.id}</span>
          </Fact>
          <Fact label="Version">{r.agent_version ?? "-"}</Fact>
          <Fact label="Started">{formatTimestamp(r.started_at)}</Fact>
          <Fact label="Completed">{formatTimestamp(r.completed_at)}</Fact>
          <Fact label="Duration">{formatDuration(durationBetween(r.started_at, r.completed_at))}</Fact>
          <Fact label="Stored">{formatTimestamp(r.created_at)}</Fact>
          {r.replay_of_run_id ? (
            <Fact label="Replay of">
              <Link
                href={`/runs/${r.replay_of_run_id}`}
                className="underline decoration-line-strong underline-offset-4 hover:text-signal hover:decoration-signal"
              >
                {shortId(r.replay_of_run_id)} (recording)
              </Link>
            </Fact>
          ) : null}
          {r.replay_of_run_id || comparison.ok ? (
            <Fact label="Verdict">
              <ComparisonFact runId={r.id} comparison={comparison} />
            </Fact>
          ) : null}
        </dl>
      </Panel>

      <section className="flex flex-col gap-5">
        <Timecode as="h2" index={1} label="input and output" />
        <div className="grid gap-3 lg:grid-cols-2">
          <JsonView label="Input" value={r.input} open />
          <JsonView label="Output" value={r.output} open />
        </div>
        <JsonView label="Metadata" value={r.metadata} />
      </section>

      <section className="flex flex-col gap-5">
        <Timecode as="h2" index={2} label="timeline" />
        {events.ok ? <RunTimeline events={events.data} /> : <ApiProblem failure={events} />}
      </section>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 border-r border-b px-4 py-3">
      <dt className="text-[10px] tracking-[0.18em] text-muted-foreground uppercase">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </div>
  );
}

function ComparisonFact({
  runId,
  comparison,
}: {
  runId: string;
  comparison: Awaited<ReturnType<typeof getComparison>>;
}) {
  if (comparison.ok) {
    const counts = comparison.data.report.counts?.by_severity ?? {};
    return (
      <Link href={`/runs/${runId}/comparison`} className="group inline-flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={comparison.data.verdict} />
        <span className="text-xs text-muted-foreground underline decoration-line-strong underline-offset-4 group-hover:text-signal">
          {counts.error ?? 0} errors · {counts.warning ?? 0} warnings · {counts.info ?? 0} info
        </span>
      </Link>
    );
  }
  if (comparison.kind === "not_found") {
    return (
      <Link href={`/runs/${runId}/comparison`} className="text-muted-foreground underline decoration-line-strong underline-offset-4 hover:text-signal">
        no report uploaded
      </Link>
    );
  }
  return <span className="text-muted-foreground">could not load ({comparison.message})</span>;
}
