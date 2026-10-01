import Link from "next/link";

import { ApiProblem } from "@/components/api-problem";
import { Micro } from "@/components/brand/primitives";
import { DataTable, ROW, THEAD } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Pagination, pageParam } from "@/components/pagination";
import { listProjects } from "@/lib/api";
import { publicApiUrl } from "@/lib/config";
import { formatTimestamp } from "@/lib/format";

// Projects and their runs change underneath the page; never prerender it.
export const dynamic = "force-dynamic";
export default async function ProjectsPage({ searchParams }: PageProps<"/projects">) {
  const page = pageParam((await searchParams).page);
  const result = await listProjects(page);

  return (
    <>
      <PageHeader title="Projects" />
      <p className="-mt-4 max-w-xl text-sm leading-7 text-muted-foreground">
        Each project holds the runs one agent records: the recordings, their replays, and the
        verdicts comparing them.
      </p>
      {!result.ok ? (
        <ApiProblem failure={result} />
      ) : result.data.total === 0 ? (
        <EmptyState />
      ) : (
        <>
          <DataTable minWidth="36rem">
            <thead className={THEAD}>
              <tr>
                <th className="px-4 py-2.5 font-medium">project</th>
                <th className="px-4 py-2.5 font-medium">description</th>
                <th className="px-4 py-2.5 text-right font-medium">runs</th>
                <th className="px-4 py-2.5 font-medium">last run</th>
              </tr>
            </thead>
            <tbody>
              {result.data.items.map((project) => (
                <tr key={project.id} className={ROW}>
                  <td className="px-4 py-3 font-medium">
                    <Link
                      href={`/projects/${project.id}`}
                      className="underline decoration-line-strong underline-offset-4 transition-colors hover:text-signal hover:decoration-signal"
                    >
                      {project.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {project.description ?? "-"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {project.run_count}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                    {project.last_run_at ? formatTimestamp(project.last_run_at) : "no runs yet"}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
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
  const create = `ADMIN="Authorization: Bearer <your admin key>"

curl -X POST ${publicApiUrl}/api/v1/projects -H "$ADMIN" \\
  -H 'Content-Type: application/json' -d '{"name": "Support agent"}'

curl -X POST ${publicApiUrl}/api/v1/projects/<project id>/keys -H "$ADMIN" \\
  -H 'Content-Type: application/json' -d '{"name": "my laptop"}'`;
  return (
    <section className="bg-grid flex flex-col gap-5 rounded-md border border-dashed border-line-strong p-6 sm:p-8">
      <div className="flex flex-col gap-2">
        <Micro tone="brand">empty</Micro>
        <h2 className="font-display text-2xl font-extrabold tracking-[-0.03em]">No projects yet</h2>
        <p className="max-w-2xl text-[13px] leading-6 text-muted-foreground">
          A project holds the runs one agent records. The dashboard only shows what the
          SDK uploads, so start by creating a project through the API with the admin key,
          then issue it a project key:
        </p>
      </div>
      <pre className="overflow-x-auto rounded-md border bg-code p-4 text-xs leading-6">
        {create}
      </pre>
      <p className="max-w-2xl text-[13px] leading-6 text-muted-foreground">
        Put the project&apos;s <code className="text-foreground">id</code> in{" "}
        <code className="text-foreground">AGENTTRACE_PROJECT_ID</code> and the key in{" "}
        <code className="text-foreground">AGENTTRACE_API_KEY</code>, then record a run with the
        Python SDK. See <strong className="text-foreground">Quickstart</strong> in the
        repository&apos;s <code>README.md</code> and <code>packages/python-sdk/README.md</code>.
        Running <code>examples/async_support_agent.py</code> and then{" "}
        <code>examples/replay_demo.py</code> fills a project with a recording, its replays
        and their comparison reports.
      </p>
    </section>
  );
}
