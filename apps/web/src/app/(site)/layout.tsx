import Link from "next/link";

import { MobileNav } from "@/components/site/mobile-nav";

const REPO_URL = "https://github.com/destroxx/agenttrace";

const NAV = [
  { href: "/#how", label: "how it works" },
  { href: "/#regressions", label: "regressions" },
  { href: "/#demo", label: "demo" },
  { href: "/#ci", label: "ci" },
  { href: "/#faq", label: "faq" },
];

function Wordmark() {
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

/**
 * The marketing site is always dark (`.dark` plus `data-surface`, which also
 * darkens the page behind it), whatever the OS theme, and set in monospace
 * throughout; only headlines use the pixel face.
 */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-surface="site" className="dark relative flex flex-1 flex-col bg-background font-mono text-foreground">
      <div aria-hidden className="bg-grid pointer-events-none fixed inset-0 opacity-40 [mask-image:linear-gradient(to_bottom,black,transparent_70%)]" />

      <p className="relative z-10 flex items-center justify-center gap-3 border-b bg-band px-4 py-2 text-center text-xs text-muted-foreground">
        <span className="size-1.5 shrink-0 rounded-full bg-pass" aria-hidden />
        <span>
          record, replay and compare all work today. semantic comparison is next.{" "}
          <Link href="/#faq" className="text-foreground underline decoration-signal underline-offset-4 hover:text-signal">
            see what is not built yet
          </Link>
        </span>
      </p>

      <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-20 w-full max-w-7xl items-center justify-between gap-6 px-5 sm:px-8">
          <Wordmark />
          <nav aria-label="Main" className="hidden items-center gap-7 text-[13px] lg:flex">
            {NAV.map((item, index) => (
              <Link
                key={item.href}
                href={item.href}
                className="group flex items-baseline gap-2 text-muted-foreground transition-colors duration-200 hover:text-foreground"
              >
                <span className="text-[10px] text-signal/70 tabular-nums group-hover:text-signal">0{index + 1}</span>
                {item.label}
              </Link>
            ))}
            <a
              href={REPO_URL}
              className="text-muted-foreground transition-colors duration-200 hover:text-foreground"
            >
              github
            </a>
            <Link
              href="/projects"
              className="ml-3 inline-flex h-10 items-center rounded-md border border-line-strong px-4 text-foreground transition-colors duration-200 hover:border-signal hover:text-signal"
            >
              open dashboard
            </Link>
          </nav>
          <div className="lg:hidden">
            <MobileNav items={[...NAV, { href: REPO_URL, label: "github" }, { href: "/projects", label: "dashboard" }]} />
          </div>
        </div>
      </header>

      <main className="relative flex flex-1 flex-col">{children}</main>
      <SiteFooter />
    </div>
  );
}

function SiteFooter() {
  const columns = [
    {
      title: "product",
      links: [
        { href: "/#how", label: "how it works" },
        { href: "/#regressions", label: "regressions" },
        { href: "/#demo", label: "replay demo" },
        { href: "/#ci", label: "suites and ci" },
      ],
    },
    {
      title: "use it",
      links: [
        { href: "/#quickstart", label: "quickstart" },
        { href: "/#sdk", label: "python sdk" },
        { href: "/#faq", label: "faq" },
        { href: "/projects", label: "dashboard" },
        { href: REPO_URL, label: "github" },
      ],
    },
  ];
  return (
    <footer className="relative border-t bg-background">
      <div className="mx-auto grid w-full max-w-7xl gap-12 px-5 py-16 sm:px-8 md:grid-cols-[2fr_1fr_1fr]">
        <div className="flex flex-col gap-5">
          <Wordmark />
          <p className="max-w-xs text-xs leading-6 text-muted-foreground">
            regression tests for ai agents, built from what their tools actually said. self-hosted.
          </p>
        </div>
        {columns.map((column) => (
          <div key={column.title} className="flex flex-col gap-4">
            <h2 className="text-[11px] tracking-[0.18em] text-muted-foreground uppercase">{column.title}</h2>
            <ul className="flex flex-col gap-3 text-[13px]">
              {column.links.map((link) => (
                <li key={link.href}>
                  <Link href={link.href} className="transition-colors hover:text-signal">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <p className="text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
            agenttrace · your recordings never leave your infrastructure
          </p>
          <p className="text-xs text-muted-foreground">
            Built with{" "}
            <span role="img" aria-label="love">
              ❤️
            </span>{" "}
            by <span className="text-foreground">Tanmay Singh</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
