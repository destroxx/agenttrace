"use client";

/**
 * Shows whether the AgentTrace API (and the database behind it) is reachable.
 *
 * The first result is fetched on the server and passed in, so this component
 * holds no data-fetching effect — it only refetches in response to a click.
 */

import { useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-4">
          API status
          <StatusBadge result={result} isPending={isPending} />
        </CardTitle>
        <CardDescription>
          <code>{apiBaseUrl}/health</code>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Details result={result} />
        <Button
          variant="outline"
          className="self-start"
          disabled={isPending}
          onClick={recheck}
        >
          {isPending ? "Checking…" : "Check again"}
        </Button>
      </CardContent>
    </Card>
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
    return <Badge variant="secondary">Checking…</Badge>;
  }
  if (!result.ok) {
    return <Badge variant="destructive">Unreachable</Badge>;
  }
  return result.report.status === "ok" ? (
    <Badge>Healthy</Badge>
  ) : (
    <Badge variant="destructive">Degraded</Badge>
  );
}

function Details({ result }: { result: HealthResult }) {
  if (!result.ok) {
    return (
      <p className="text-sm text-muted-foreground">
        Could not reach the API ({result.error}). Start it with{" "}
        <code>uvicorn app.main:app --reload</code> in <code>apps/api</code>.
      </p>
    );
  }

  const database = result.report.checks.database;

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
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
