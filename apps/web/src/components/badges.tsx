/**
 * Status, verdict and severity badges.
 *
 * Every badge carries its meaning in text, not only in colour, so it reads
 * the same in both themes and to anyone who cannot tell red from green.
 */

import { cn } from "cn";

import { Badge } from "@/components/ui/badge";
import type { RunStatus, Severity, Verdict } from "@/lib/api";

const PASS = "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400";
const WARNING = "bg-amber-500/15 text-amber-700 dark:text-amber-400";

export function StatusBadge({ status }: { status: RunStatus | string }) {
  if (status === "completed") {
    return <Badge variant="secondary">completed</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">failed</Badge>;
  }
  return <Badge variant="outline">{status}</Badge>;
}

export function VerdictBadge({
  verdict,
  className,
}: {
  verdict: Verdict;
  className?: string;
}) {
  return verdict === "pass" ? (
    <Badge className={cn(PASS, className)}>PASS</Badge>
  ) : (
    <Badge variant="destructive" className={className}>
      FAIL
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  if (severity === "error") {
    return <Badge variant="destructive">error</Badge>;
  }
  if (severity === "warning") {
    return <Badge className={WARNING}>warning</Badge>;
  }
  return <Badge variant="secondary">{severity}</Badge>;
}

export function ReplayBadge() {
  return (
    <Badge variant="outline" title="This run replayed a recording">
      replay
    </Badge>
  );
}
