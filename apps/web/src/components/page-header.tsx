import Link from "next/link";
import type { ReactNode } from "react";

import { Display } from "@/components/brand/primitives";

export interface Crumb {
  label: string;
  href?: string;
}

/**
 * Breadcrumbs as the site's micro labels, a dot-matrix title and optional
 * trailing content, the same on every screen.
 */
export function PageHeader({
  crumbs = [],
  title,
  children,
}: {
  crumbs?: Crumb[];
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4">
      {crumbs.length > 0 ? (
        <nav aria-label="Breadcrumb" className="text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
          {crumbs.map((crumb, index) => (
            <span key={`${crumb.label}-${index}`}>
              {index > 0 ? (
                <span className="mx-2 text-line-strong" aria-hidden>
                  /
                </span>
              ) : null}
              {crumb.href ? (
                <Link href={crumb.href} className="transition-colors hover:text-signal">
                  {crumb.label}
                </Link>
              ) : (
                crumb.label
              )}
            </span>
          ))}
        </nav>
      ) : null}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
        <Display as="h1" className="min-w-0 text-4xl break-words md:text-5xl">
          {title}
        </Display>
        {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
      </div>
    </header>
  );
}
