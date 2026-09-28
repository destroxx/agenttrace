import Link from "next/link";

import { ApiProblem } from "@/components/api-problem";
import { PageHeader } from "@/components/page-header";
import { Pagination, pageParam } from "@/components/pagination";
import { listProjects } from "@/lib/api";
import { apiBaseUrl } from "@/lib/config";
import { formatTimestamp } from "@/lib/format";

// Projects and their runs change underneath the page; never prerender it.
export const dynamic = "force-dynamic";

export default async function ProjectsPage({ searchParams }: PageProps<"/projects">) {
  const page = pageParam((await searchParams).page);
  const result = await listProjects(page);

  return (
    <>
      <PageHeader title="Projects" />
      <p className="-mt-3 max-w-2xl text-sm text-muted-foreground">
        Each project holds the runs one agent records: the recordings, their replays, and the
        verdicts comparing them.
      </p>
      {!result.ok ? (
        <ApiProblem failure={result} />
      ) : result.data.total === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">Project</th>
                  <th className="px-4 py-2 font-medium">Description</th>
                  <th className="px-4 py-2 text-right font-medium">Runs</th>
                  <th className="px-4 py-2 font-medium">Last run</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((project) => (
                  <tr key={project.id} className="border-t hover:bg-muted/30">
                    <td className="px-4 py-2 font-medium">
                      <Link
                        href={`/projects/${project.id}`}
                        className="hover:underline underline-offset-4"
                      >
                        {project.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {project.description ?? "-"}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {project.run_count}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-muted-foreground">
                      {project.last_run_at ? formatTimestamp(project.last_run_at) : "no runs yet"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={result.data.page}
            pageSize={result.data.page_size}
            total={result.data.total}
            href={(n) => `/projects?page=${n}`}
          />
        </>
      )}
    </>
  );
}

function EmptyState() {
  const create = `curl -X POST ${apiBaseUrl}/api/v1/projects \\
  -H 'Content-Type: application/json' \\
  -d '{"name": "Support agent"}'`;
  return (
    <section className="bg-grid flex flex-col gap-4 rounded-xl border border-dashed bg-card p-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">No projects yet</h2>
        <p className="text-sm text-muted-foreground">
          A project holds the runs one agent records. The dashboard only shows what the
          SDK uploads, so start by creating a project through the API:
        </p>
      </div>
      <pre className="overflow-x-auto rounded-md border bg-background p-3 font-mono text-xs">
        {create}
      </pre>
      <p className="text-sm text-muted-foreground">
        Put the returned <code>id</code> in <code>AGENTTRACE_PROJECT_ID</code> and record a run
        with the Python SDK. See <strong>Quickstart</strong> in the repository&apos;s{" "}
        <code>README.md</code> and <code>packages/python-sdk/README.md</code>. Running{" "}
        <code>examples/async_support_agent.py</code> and then{" "}
        <code>examples/replay_demo.py</code> fills a project with a recording, its replays
        and their comparison reports.
      </p>
    </section>
  );
}
