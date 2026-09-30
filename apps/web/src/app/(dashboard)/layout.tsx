import Link from "next/link";
import { Suspense } from "react";

import { MobileNav } from "@/components/brand/mobile-nav";
import { REPO_URL, Wordmark } from "@/components/brand/wordmark";
import {
  HealthIndicator,
  HealthIndicatorFallback,
} from "@/components/health-indicator";

const NAV = [
  { href: "/projects", label: "projects" },
  { href: "/", label: "site" },
  { href: REPO_URL, label: "github" },
];

/**
 * The dashboard is always dark, like the marketing site (`.dark` plus
 * `data-surface`, see globals.css): one brand from the site to the app, and
 * one theme to design and check instead of two. Same header family as the
 * site, with the API's health where the site has its call to action.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-surface="app" className="dark relative flex flex-1 flex-col bg-background font-mono text-foreground">
      <div aria-hidden className="bg-grid pointer-events-none fixed inset-0 opacity-30 [mask-image:linear-gradient(to_bottom,black,transparent_45%)]" />

      <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-20 w-full max-w-7xl items-center justify-between gap-4 px-5 sm:px-8">
          <div className="flex items-center gap-4">
            <Wordmark />
            <span className="hidden h-5 w-px bg-line-strong sm:block" aria-hidden />
            <span className="hidden text-[11px] tracking-[0.18em] text-muted-foreground uppercase sm:inline">
              dashboard
            </span>
          </div>
          <div className="flex items-center gap-5 md:gap-7">
            <nav aria-label="Main" className="hidden items-center gap-7 text-[13px] md:flex">
              {NAV.map((item) =>
                item.href.startsWith("http") ? (
                  <a
                    key={item.href}
                    href={item.href}
                    className="text-muted-foreground transition-colors duration-200 hover:text-foreground"
                  >
                    {item.label}
                  </a>
                ) : (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="text-muted-foreground transition-colors duration-200 hover:text-foreground"
                  >
                    {item.label}
                  </Link>
                ),
              )}
            </nav>
            <Suspense fallback={<HealthIndicatorFallback />}>
              <HealthIndicator />
            </Suspense>
            <MobileNav items={NAV} />
          </div>
        </div>
      </header>

      <main className="relative mx-auto flex w-full max-w-7xl min-w-0 flex-1 flex-col gap-10 px-5 py-12 sm:px-8 md:py-16">
        {children}
      </main>

      <footer className="relative border-t">
        <p className="mx-auto w-full max-w-7xl px-5 py-5 text-[11px] tracking-[0.18em] text-muted-foreground uppercase sm:px-8">
          agenttrace · read-only · your recordings never leave your infrastructure
        </p>
      </footer>
    </div>
  );
}
