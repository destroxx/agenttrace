import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { ReplayBadge, StatusBadge, VerdictBadge } from "@/components/badges";
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
    { label: "Projects", href: "/" },
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
        {r.replay_of_run_id ? <ReplayBadge /> : null}
        {comparison.ok ? (
          <Link href={`/runs/${r.id}/comparison`} title="Open the comparison report">
            <VerdictBadge verdict={comparison.data.verdict} />
          </Link>
        ) : null}
      </PageHeader>

      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
        <Fact label="Run">
          <code className="text-xs">{r.id}</code>
        </Fact>
        <Fact label="Version">
          <span className="font-mono text-xs">{r.agent_version ?? "—"}</span>
        </Fact>
        <Fact label="Started">{formatTimestamp(r.started_at)}</Fact>
        <Fact label="Completed">{formatTimestamp(r.completed_at)}</Fact>
        <Fact label="Duration">{formatDuration(durationBetween(r.started_at, r.completed_at))}</Fact>
        <Fact label="Stored">{formatTimestamp(r.created_at)}</Fact>
        {r.replay_of_run_id ? (
          <Fact label="Replay of">
            <Link
              href={`/runs/${r.replay_of_run_id}`}
              className="font-mono text-xs underline underline-offset-4"
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

      <div className="grid gap-3 lg:grid-cols-2">
        <JsonView label="Input" value={r.input} open />
        <JsonView label="Output" value={r.output} open />
      </div>
      <JsonView label="Metadata" value={r.metadata} />

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Timeline</h2>
        {events.ok ? <RunTimeline events={events.data} /> : <ApiProblem failure={events} />}
      </section>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </>
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
      <Link href={`/runs/${runId}/comparison`} className="inline-flex items-center gap-2 underline-offset-4 hover:underline">
        <VerdictBadge verdict={comparison.data.verdict} />
        <span className="text-xs text-muted-foreground">
          {counts.error ?? 0} errors · {counts.warning ?? 0} warnings · {counts.info ?? 0} info
        </span>
      </Link>
    );
  }
  if (comparison.kind === "not_found") {
    return (
      <Link href={`/runs/${runId}/comparison`} className="text-muted-foreground underline-offset-4 hover:underline">
        no report uploaded
      </Link>
    );
  }
  return <span className="text-muted-foreground">could not load ({comparison.message})</span>;
}
