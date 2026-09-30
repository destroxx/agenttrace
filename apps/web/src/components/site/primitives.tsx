/**
 * Building blocks only the marketing site's sections use. Server-only markup:
 * nothing here needs client JavaScript. The brand's shared pieces (Micro,
 * Timecode, Display, Panel, ButtonLink, VerdictChip, ...) live in
 * `components/brand/primitives.tsx`, which the dashboard uses too.
 */

import type { ReactNode } from "react";

import { Display, Timecode } from "@/components/brand/primitives";
import { sectionIndex, sectionLabel, type SectionId } from "@/components/site/sections";

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
