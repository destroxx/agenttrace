import Link from "next/link";
import { Suspense } from "react";

import {
  HealthIndicator,
  HealthIndicatorFallback,
} from "@/components/health-indicator";
import { Logo } from "@/components/logo";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/65">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <nav className="flex items-center gap-6 text-sm">
            <Logo href="/" />
            <span className="h-5 w-px bg-border" aria-hidden />
            <Link
              href="/projects"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Projects
            </Link>
          </nav>
          <Suspense fallback={<HealthIndicatorFallback />}>
            <HealthIndicator />
          </Suspense>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
        {children}
      </main>
    </>
  );
}
