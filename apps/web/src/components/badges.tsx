/**
 * Status, verdict and severity badges, in the site's tag style: small, square
 * and letter-spaced, like the chips in the landing page's dashboard picture.
 *
 * Every badge carries its meaning in text, not only in colour, so it reads
 * the same to anyone who cannot tell red from green.
 */

import type { ReactNode } from "react";

import { VerdictChip } from "@/components/brand/primitives";
import type { RunStatus, Severity, Verdict } from "@/lib/api";

const TAG = "inline-flex h-5 shrink-0 items-center gap-1.5 rounded-sm px-2 text-[10px] font-medium tracking-[0.12em] whitespace-nowrap uppercase";

const LOOK = {
  neutral: "bg-secondary text-secondary-foreground",
  outline: "border border-line-strong text-muted-foreground",
  pass: "bg-pass/12 text-pass",
  fail: "bg-fail/12 text-fail",
  warn: "bg-warn/12 text-warn",
  live: "border border-signal/40 text-signal",
};

export function Tag({
  look = "neutral",
  title,
  children,
}: {
  look?: keyof typeof LOOK;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className={`${TAG} ${LOOK[look]}`} title={title}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: RunStatus | string }) {
  if (status === "completed") {
    return <Tag>completed</Tag>;
  }
  if (status === "failed") {
    return <Tag look="fail">failed</Tag>;
  }
  if (status === "running") {
    return (
      <Tag look="live">
        <span className="animate-trace size-1.5 rounded-full bg-current" aria-hidden />
        running
      </Tag>
    );
  }
  return <Tag look="outline">{status}</Tag>;
}

export function VerdictBadge({
  verdict,
  className,
}: {
  verdict: Verdict;
  className?: string;
}) {
  return <VerdictChip verdict={verdict} className={className} />;
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  if (severity === "error") {
    return <Tag look="fail">error</Tag>;
  }
  if (severity === "warning") {
    return <Tag look="warn">warning</Tag>;
  }
  return <Tag>{severity}</Tag>;
}

export function ReplayBadge() {
  return (
    <Tag look="outline" title="This run replayed a recording">
      replay
    </Tag>
  );
}
