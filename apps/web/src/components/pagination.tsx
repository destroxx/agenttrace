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
  const box = "inline-flex h-10 items-center rounded-md border px-4";
  const link = `${box} border-line-strong text-foreground transition-colors hover:border-signal hover:text-signal`;
  const disabled = `${box} text-muted-foreground/60`;
  return (
    <nav className="flex flex-wrap items-center gap-3 text-[13px]" aria-label="Pagination">
      {page > 1 ? (
        <Link className={link} href={href(page - 1)}>
          newer
        </Link>
      ) : (
        <span className={disabled}>newer</span>
      )}
      <span className="text-muted-foreground tabular-nums">
        page {page} of {pages} · {total} total
      </span>
      {page < pages ? (
        <Link className={link} href={href(page + 1)}>
          older
        </Link>
      ) : (
        <span className={disabled}>older</span>
      )}
    </nav>
  );
}

/** A positive page number from a search param, defaulting to 1. */
export function pageParam(value: string | string[] | undefined): number {
  const parsed = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}
