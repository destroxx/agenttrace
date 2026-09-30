/**
 * Formatted JSON, collapsible with a native <details> — no client JavaScript,
 * so it works in a Server Component and before hydration.
 */

import { formatJson } from "@/lib/format";

export function JsonView({
  label,
  value,
  open = false,
}: {
  label: string;
  value: unknown;
  open?: boolean;
}) {
  return (
    <details open={open} className="group min-w-0 overflow-hidden rounded-md border bg-code">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 select-none hover:bg-card [&::-webkit-details-marker]:hidden">
        <span className="size-2 rounded-full bg-signal" aria-hidden />
        <span className="text-[11px] tracking-[0.18em] text-muted-foreground uppercase">{label}</span>
        {value === null || value === undefined ? (
          <span className="text-xs text-muted-foreground">none</span>
        ) : null}
        <span className="ml-auto inline-block text-muted-foreground transition-transform group-open:rotate-90" aria-hidden>
          ›
        </span>
      </summary>
      <JsonBlock value={value} className="border-t" />
    </details>
  );
}

export function JsonBlock({
  value,
  className = "",
}: {
  value: unknown;
  className?: string;
}) {
  return (
    <pre
      className={`max-h-96 overflow-auto bg-code p-4 font-mono text-xs leading-6 whitespace-pre ${className}`}
    >
      {formatJson(value)}
    </pre>
  );
}
