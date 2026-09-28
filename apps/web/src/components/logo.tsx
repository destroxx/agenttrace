import Link from "next/link";

/**
 * The mark is a recorded trace: three steps on a line, the last one lit —
 * the same shape as a run's timeline.
 */
export function LogoMark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden fill="none">
      <rect x="1" y="1" width="22" height="22" rx="6" className="fill-foreground/5 stroke-border" />
      <path d="M5 12h14" className="stroke-muted-foreground/60" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="7" cy="12" r="2" className="fill-muted-foreground" />
      <circle cx="12" cy="12" r="2" className="fill-muted-foreground" />
      <circle cx="17" cy="12" r="2.5" className="fill-pass" />
    </svg>
  );
}

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 rounded-md font-semibold tracking-tight focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <LogoMark />
      <span>
        AgentTrace
      </span>
    </Link>
  );
}
