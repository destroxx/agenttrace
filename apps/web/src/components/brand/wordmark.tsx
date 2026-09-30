import Link from "next/link";

export const REPO_URL = "https://github.com/destroxx/agenttrace";

/** The lit recording light and the dot-matrix name, in the site's and the dashboard's headers. */
export function Wordmark() {
  return (
    <Link
      href="/"
      className="flex items-center gap-2.5 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-signal"
    >
      <span aria-hidden className="relative flex size-3 items-center justify-center">
        <span className="animate-trace absolute size-3 rounded-full bg-signal/30" />
        <span className="size-2 rounded-full bg-signal" />
      </span>
      <span className="font-display text-2xl leading-none font-black tracking-tight">agenttrace</span>
    </Link>
  );
}
