import Link from "next/link";

/** Previous / next links over the API's 1-based pages. */
export function Pagination({
  page,
  pageSize,
  total,
  href,
}: {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) {
    return null;
  }
  const link = "rounded-md border px-3 py-1.5 hover:bg-muted";
  const disabled = "rounded-md border px-3 py-1.5 text-muted-foreground opacity-50";
  return (
    <nav className="flex items-center gap-3 text-sm" aria-label="Pagination">
      {page > 1 ? (
        <Link className={link} href={href(page - 1)}>
          ← Newer
        </Link>
      ) : (
        <span className={disabled}>← Newer</span>
      )}
      <span className="text-muted-foreground">
        Page {page} of {pages} · {total} total
      </span>
      {page < pages ? (
        <Link className={link} href={href(page + 1)}>
          Older →
        </Link>
      ) : (
        <span className={disabled}>Older →</span>
      )}
    </nav>
  );
}

/** A positive page number from a search param, defaulting to 1. */
export function pageParam(value: string | string[] | undefined): number {
  const parsed = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}
