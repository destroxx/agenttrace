/**
 * Building blocks shared by the marketing site's sections. Server-only markup:
 * nothing here needs client JavaScript.
 *
 * Visual language, borrowed from the product itself: a recording. Dot-matrix
 * display headlines like a tape counter, timecode section markers, panels with
 * a timeline ruler along the top, and one brand colour (tape-deck orange).
 * Red, green and yellow only ever mean fail, pass and warning.
 * Copy rules: no em-dashes, no arrows on buttons.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { sectionIndex, sectionLabel, type SectionId } from "@/components/site/sections";

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
 * is hidden from them; the label stays readable.
 */
export function Timecode({ index, label }: { index: number; label: string }) {
  return (
    <p className="flex items-center gap-4 text-xs text-muted-foreground">
      <span aria-hidden className="font-display text-base font-extrabold tracking-wider text-signal tabular-nums">
        00:{String(index).padStart(2, "0")}
      </span>
      <span className="h-px w-10 bg-line-strong" aria-hidden />
      <span className="tracking-[0.18em] uppercase">{label}</span>
    </p>
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

export function Section({
  id,
  title,
  lead,
  children,
  band = false,
}: {
  id: SectionId;
  title: ReactNode;
  lead?: ReactNode;
  children: ReactNode;
  band?: boolean;
}) {
  return (
    <section id={id} className={`scroll-mt-20 border-t ${band ? "bg-band" : ""}`}>
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-14 px-5 py-24 sm:px-8 md:py-32">
        <header className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-end">
          <div className="flex flex-col gap-6">
            <Timecode index={sectionIndex(id)} label={sectionLabel(id)} />
            <Display className="text-4xl md:text-5xl">{title}</Display>
          </div>
          {lead ? <p className="max-w-xl text-sm leading-7 text-muted-foreground md:text-[15px] lg:justify-self-end">{lead}</p> : null}
        </header>
        {children}
      </div>
    </section>
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

/** A terminal or editor pane around preformatted, hand-highlighted text. */
export function Window({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 overflow-hidden rounded-md border bg-code ${className}`}>
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <span className="size-2 rounded-full bg-signal" aria-hidden />
        <span className="truncate text-xs text-muted-foreground">{title}</span>
      </div>
      <pre className="overflow-x-auto p-5 text-[13px] leading-6">{children}</pre>
    </div>
  );
}

// Syntax colours for the hand-highlighted samples.
export const K = ({ children }: { children: ReactNode }) => <span className="text-syntax-keyword">{children}</span>;
export const S = ({ children }: { children: ReactNode }) => <span className="text-syntax-string">{children}</span>;
export const F = ({ children }: { children: ReactNode }) => <span className="text-syntax-function">{children}</span>;
export const C = ({ children }: { children: ReactNode }) => <span className="text-muted-foreground/70">{children}</span>;
export const D = ({ children }: { children: ReactNode }) => <span className="text-warn">{children}</span>;
export const PASS = ({ children = "PASS" }: { children?: ReactNode }) => <span className="text-pass">{children}</span>;
export const FAIL = ({ children = "FAIL" }: { children?: ReactNode }) => <span className="text-fail">{children}</span>;

const base =
  "inline-flex h-12 items-center justify-center rounded-md px-6 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-signal";

/** A solid tape-orange primary and a hairline secondary. */
export function ButtonLink({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
}) {
  const look =
    variant === "primary"
      ? "bg-signal text-signal-foreground hover:bg-signal/85"
      : "border border-line-strong text-foreground hover:border-foreground/60 hover:bg-card";
  return (
    <Link href={href} className={`${base} ${look}`}>
      {children}
    </Link>
  );
}

export function VerdictChip({ verdict }: { verdict: "pass" | "fail" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-[10px] font-medium tracking-[0.12em] ${
        verdict === "pass" ? "bg-pass/12 text-pass" : "bg-fail/12 text-fail"
      }`}
    >
      <span className="size-1 rounded-full bg-current" aria-hidden />
      {verdict.toUpperCase()}
    </span>
  );
}
