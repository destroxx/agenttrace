import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { ReplayBadge, StatusBadge, VerdictBadge } from "@/components/badges";
import { PageHeader } from "@/components/page-header";
import { Pagination, pageParam } from "@/components/pagination";
import {
  getProject,
  isUuid,
  listRuns,
  RUN_STATUSES,
  type RunStatus,
  type RunSummary,
} from "@/lib/api";
import { formatDuration, formatTimestamp, shortId } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ProjectPage({
  params,
  searchParams,
}: PageProps<"/projects/[id]">) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }
  const query = await searchParams;
  const page = pageParam(query.page);
  const status = RUN_STATUSES.find((s) => s === query.status);

  const [project, runs] = await Promise.all([
    getProject(id),
    listRuns(id, { page, status }),
  ]);
  if (!project.ok && project.kind === "not_found") {
    notFound();
  }
  if (!project.ok) {
    return <ApiProblem failure={project} />;
  }

  const href = (next: { page?: number; status?: RunStatus }) => {
    const search = new URLSearchParams();
    if (next.status) search.set("status", next.status);
    if (next.page && next.page > 1) search.set("page", String(next.page));
    const text = search.toString();
    return `/projects/${id}${text ? `?${text}` : ""}`;
  };

  return (
    <>
      <PageHeader crumbs={[{ label: "Projects", href: "/" }]} title={project.data.name} />
      {project.data.description ? (
        <p className="-mt-3 text-sm text-muted-foreground">{project.data.description}</p>
      ) : null}

      <nav className="flex flex-wrap items-center gap-2 text-sm" aria-label="Filter by status">
        <span className="text-muted-foreground">Status:</span>
        {[undefined, ...RUN_STATUSES].map((option) => {
          const active = option === status;
          return (
            <Link
              key={option ?? "all"}
              href={href({ status: option })}
              aria-current={active ? "page" : undefined}
              className={`rounded-md border px-2.5 py-1 ${
                active ? "bg-foreground text-background" : "hover:bg-muted"
              }`}
            >
              {option ?? "all"}
            </Link>
          );
        })}
      </nav>

      {!runs.ok ? (
        <ApiProblem failure={runs} />
      ) : runs.data.total === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          {status
            ? `No ${status} runs in this project.`
            : "No runs yet. Runs appear here once an agent traced with the SDK uploads them."}
        </p>
      ) : (
        <>
          <RunsTable runs={runs.data.items} />
          <Pagination
            page={runs.data.page}
            pageSize={runs.data.page_size}
            total={runs.data.total}
            href={(n) => href({ page: n, status })}
          />
        </>
      )}
    </>
  );
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            <th className="px-4 py-2 font-medium">Run</th>
            <th className="px-4 py-2 font-medium">Version</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 text-right font-medium">Duration</th>
            <th className="px-4 py-2 text-right font-medium">Events</th>
            <th className="px-4 py-2 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-t align-top hover:bg-muted/30">
              <td className="px-4 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/runs/${run.id}`} className="font-medium hover:underline underline-offset-4">
                    {run.agent_name}
                  </Link>
                  <code className="text-xs text-muted-foreground">{shortId(run.id)}</code>
                  {run.replay_of_run_id ? <ReplayBadge /> : null}
                </div>
                {run.replay_of_run_id ? (
                  <div className="text-xs text-muted-foreground">
                    replay of{" "}
                    <Link
                      href={`/runs/${run.replay_of_run_id}`}
                      className="font-mono underline-offset-4 hover:underline"
                    >
                      {shortId(run.replay_of_run_id)}
                    </Link>
                  </div>
                ) : null}
              </td>
              <td className="px-4 py-2 font-mono text-xs">{run.agent_version ?? "—"}</td>
              <td className="px-4 py-2">
                <StatusBadge status={run.status} />
              </td>
              <td className="px-4 py-2 whitespace-nowrap text-muted-foreground">
                {formatTimestamp(run.started_at)}
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{formatDuration(run.duration_ms)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{run.event_count}</td>
              <td className="px-4 py-2">
                {run.verdict ? (
                  <Link href={`/runs/${run.id}/comparison`} title="Open the comparison report">
                    <VerdictBadge verdict={run.verdict} />
                  </Link>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
