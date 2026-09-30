import type { ReactNode } from "react";

import { Panel } from "@/components/brand/primitives";

/**
 * A dashboard table in a ruled panel, styled like the landing page's picture
 * of the dashboard. It stays a real <table>; on a narrow screen it scrolls
 * sideways inside the panel instead of widening the page.
 */
export function DataTable({ minWidth, children }: { minWidth: string; children: ReactNode }) {
  return (
    <Panel>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]" style={{ minWidth }}>
          {children}
        </table>
      </div>
    </Panel>
  );
}

/** Column heads in the site's micro-label style. */
export const THEAD =
  "border-b bg-muted/50 text-left text-[10px] tracking-[0.18em] text-muted-foreground uppercase";

/** A body row: a hairline above, and the card colour under the pointer. */
export const ROW = "border-t transition-colors first:border-t-0 hover:bg-card";
