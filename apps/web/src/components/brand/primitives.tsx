/**
 * The brand's building blocks, shared by the marketing site and the dashboard
 * so the product looks like its own advertisement. Server-safe markup: nothing
 * here needs client JavaScript.
 *
 * Visual language, borrowed from the product itself: a recording. Dot-matrix
 * display headlines like a tape counter, timecode section markers, panels with
 * a timeline ruler along the top, and one brand colour (tape-deck orange).
 * Red, green and yellow only ever mean fail, pass and warning.
 * Copy rules: no em-dashes, no arrows on buttons.
 */

import Link from "next/link";
import type { ReactNode } from "react";

type Tone = "brand" | "pass" | "fail" | "warn" | "ink";

const TONE: Record<Tone, string> = {
  brand: "text-signal",
  pass: "text-pass",
  fail: "text-fail",
  warn: "text-warn",
  ink: "text-muted-foreground",
};

/** Letter-spaced uppercase micro label. */
export function Micro({ children, tone = "ink", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={`text-[11px] tracking-[0.18em] uppercase ${TONE[tone]} ${className}`}>{children}</span>;
}

/** A recorder's status light: `● rec`, `● replaying`. */
export function RecChip({ children, tone = "brand" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border border-current/30 px-3 py-1 text-[11px] tracking-[0.14em] uppercase ${TONE[tone]}`}>
      <span className="animate-trace size-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  );
}

/**
 * Section marker as a timecode: `00:03  regressions`. The number is
 * decoration (screen readers would read "zero zero colon zero three"), so it
 * is hidden from them; the label stays readable. `as="h2"` lets the dashboard
 * use it as a real heading.
 */
export function Timecode({ index, label, as: Tag = "p" }: { index: number; label: string; as?: "p" | "h2" }) {
  return (
    <Tag className="flex items-center gap-4 text-xs text-muted-foreground">
      <span aria-hidden className="font-display text-base font-extrabold tracking-wider text-signal tabular-nums">
        00:{String(index).padStart(2, "0")}
      </span>
      <span className="h-px w-10 bg-line-strong" aria-hidden />
      <span className="tracking-[0.18em] uppercase">{label}</span>
    </Tag>
  );
}

/** Dot-matrix headline. */
export function Display({
  as: Tag = "h2",
  children,
  className = "",
}: {
  as?: "h1" | "h2" | "h3";
  children: ReactNode;
  className?: string;
}) {
  return (
    <Tag className={`font-display leading-[1.02] font-extrabold tracking-[-0.045em] text-balance ${className}`}>{children}</Tag>
  );
}

/** A ruler of tick marks, like the top edge of a timeline. */
export function Ruler({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`h-2.5 border-b [background-image:repeating-linear-gradient(to_right,var(--line-strong)_0_1px,transparent_1px_12px),repeating-linear-gradient(to_right,var(--muted-foreground)_0_1px,transparent_1px_60px)] [background-size:100%_50%,100%_100%] bg-no-repeat [background-position:bottom,bottom] ${className}`}
    />
  );
}

/** A panel with a timeline ruler across its top. */
export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`overflow-hidden rounded-md border bg-code ${className}`}>
      <Ruler />
      {children}
    </div>
  );
}

/**
 * A solid tape-orange primary and a hairline secondary. Exported as classes
 * too, for the dashboard's `<button>`s (retry, check again) that are not links.
 */
export function buttonClasses(variant: "primary" | "secondary" = "primary"): string {
  const base =
    "inline-flex h-12 cursor-pointer items-center justify-center rounded-md px-6 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-signal disabled:cursor-default disabled:opacity-50";
  const look =
    variant === "primary"
      ? "bg-signal text-signal-foreground hover:bg-signal/85"
      : "border border-line-strong text-foreground hover:border-foreground/60 hover:bg-card";
  return `${base} ${look}`;
}

export function ButtonLink({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
}) {
  return (
    <Link href={href} className={buttonClasses(variant)}>
      {children}
    </Link>
  );
}

export function VerdictChip({ verdict, className = "" }: { verdict: "pass" | "fail"; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-[10px] font-medium tracking-[0.12em] ${
        verdict === "pass" ? "bg-pass/12 text-pass" : "bg-fail/12 text-fail"
      } ${className}`}
    >
      <span className="size-1 rounded-full bg-current" aria-hidden />
      {verdict.toUpperCase()}
    </span>
  );
}
