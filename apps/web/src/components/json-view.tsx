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
    <details open={open} className="group rounded-lg border">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium select-none">
        {label}
        {value === null || value === undefined ? (
          <span className="ml-2 font-normal text-muted-foreground">none</span>
        ) : null}
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
      className={`max-h-96 overflow-auto bg-muted/40 p-3 font-mono text-xs leading-relaxed whitespace-pre ${className}`}
    >
      {formatJson(value)}
    </pre>
  );
}
