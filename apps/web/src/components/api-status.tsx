"use client";

/**
 * Shows whether the AgentTrace API (and the database behind it) is reachable.
 *
 * The first result is fetched on the server and passed in, so this component
 * holds no data-fetching effect — it only refetches in response to a click.
 */

import { useState, useTransition } from "react";

import { Tag } from "@/components/badges";
import { buttonClasses, Micro, Panel } from "@/components/brand/primitives";
import { apiBaseUrl } from "@/lib/config";
import { fetchHealth, type HealthResult } from "@/lib/health";

export function ApiStatus({ initialResult }: { initialResult: HealthResult }) {
  const [result, setResult] = useState<HealthResult>(initialResult);
  const [isPending, startTransition] = useTransition();

  const recheck = () => {
    startTransition(async () => {
      setResult(await fetchHealth());
    });
  };

  return (
    <Panel className="w-full">
      <div className="flex flex-col gap-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <Micro>api status</Micro>
            <code className="text-[13px] break-all">{apiBaseUrl}/health</code>
          </div>
          <StatusBadge result={result} isPending={isPending} />
        </div>
        <Details result={result} />
        <button
          type="button"
          className={`${buttonClasses("secondary")} self-start`}
          disabled={isPending}
          onClick={recheck}
        >
          {isPending ? "Checking…" : "Check again"}
        </button>
      </div>
    </Panel>
  );
}

function StatusBadge({
  result,
  isPending,
}: {
  result: HealthResult;
  isPending: boolean;
}) {
  if (isPending) {
    return <Tag>checking…</Tag>;
  }
  if (!result.ok) {
    return <Tag look="fail">unreachable</Tag>;
  }
  return result.report.status === "ok" ? (
    <Tag look="pass">healthy</Tag>
  ) : (
    <Tag look="fail">degraded</Tag>
  );
}

function Details({ result }: { result: HealthResult }) {
  if (!result.ok) {
    return (
      <p className="text-[13px] leading-6 text-muted-foreground">
        Could not reach the API ({result.error}). Start it with{" "}
        <code>uvicorn app.main:app --reload</code> in <code>apps/api</code>.
      </p>
    );
  }

  const database = result.report.checks.database;

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-[13px]">
      <dt className="text-muted-foreground">Version</dt>
      <dd>{result.report.version}</dd>
      <dt className="text-muted-foreground">Environment</dt>
      <dd>{result.report.environment}</dd>
      <dt className="text-muted-foreground">Database</dt>
      <dd>
        {database?.status ?? "unknown"}
        {database?.latency_ms != null ? ` · ${database.latency_ms} ms` : ""}
        {database?.error ? ` · ${database.error}` : ""}
      </dd>
    </dl>
  );
}
