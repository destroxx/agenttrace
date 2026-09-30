import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiProblem } from "@/components/api-problem";
import { ReplayBadge, StatusBadge, VerdictBadge } from "@/components/badges";
import { Micro } from "@/components/brand/primitives";
import { DataTable, ROW, THEAD } from "@/components/data-table";
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
      <PageHeader crumbs={[{ label: "Projects", href: "/projects" }]} title={project.data.name} />
      {project.data.description ? (
        <p className="-mt-4 max-w-xl text-sm leading-7 text-muted-foreground">{project.data.description}</p>
      ) : null}

      <nav className="flex flex-wrap items-center gap-2 text-[13px]" aria-label="Filter by status">
        <Micro className="mr-2">status</Micro>
        {[undefined, ...RUN_STATUSES].map((option) => {
          const active = option === status;
          return (
            <Link
              key={option ?? "all"}
              href={href({ status: option })}
              aria-current={active ? "page" : undefined}
              className={`inline-flex h-9 items-center rounded-md border px-3.5 transition-colors ${
                active
                  ? "border-signal bg-signal/10 text-signal"
                  : "border-line-strong text-muted-foreground hover:border-foreground/60 hover:text-foreground"
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
        <p className="bg-grid rounded-md border border-dashed border-line-strong p-6 text-[13px] leading-6 text-muted-foreground sm:p-8">
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
    <DataTable minWidth="54rem">
      <thead className={THEAD}>
        <tr>
          <th className="px-4 py-2.5 font-medium">run</th>
          <th className="px-4 py-2.5 font-medium">version</th>
          <th className="px-4 py-2.5 font-medium">status</th>
          <th className="px-4 py-2.5 font-medium">started</th>
          <th className="px-4 py-2.5 text-right font-medium">duration</th>
          <th className="px-4 py-2.5 text-right font-medium">events</th>
          <th className="px-4 py-2.5 font-medium">verdict</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id} className={`${ROW} align-top`}>
            <td className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/runs/${run.id}`}
                  className="font-medium underline decoration-line-strong underline-offset-4 transition-colors hover:text-signal hover:decoration-signal"
                >
                  {run.agent_name}
                </Link>
                <span className="text-xs text-muted-foreground">{shortId(run.id)}</span>
                {run.replay_of_run_id ? <ReplayBadge /> : null}
              </div>
              {run.replay_of_run_id ? (
                <div className="mt-1 text-[11px] text-muted-foreground">
                  replay of{" "}
                  <Link
                    href={`/runs/${run.replay_of_run_id}`}
                    className="underline decoration-line-strong underline-offset-4 hover:text-signal"
                  >
                    {shortId(run.replay_of_run_id)}
                  </Link>
                </div>
              ) : null}
            </td>
            <td className="px-4 py-3 text-xs">{run.agent_version ?? "-"}</td>
            <td className="px-4 py-3">
              <StatusBadge status={run.status} />
            </td>
            <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
              {formatTimestamp(run.started_at)}
            </td>
            <td className="px-4 py-3 text-right whitespace-nowrap tabular-nums">{formatDuration(run.duration_ms)}</td>
            <td className="px-4 py-3 text-right tabular-nums">{run.event_count}</td>
            <td className="px-4 py-3">
              {run.verdict ? (
                <Link
                  href={`/runs/${run.id}/comparison`}
                  title="Open the comparison report"
                  className="inline-flex rounded-sm"
                >
                  <VerdictBadge verdict={run.verdict} />
                </Link>
              ) : (
                <span className="text-muted-foreground">-</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
