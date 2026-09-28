import Link from "next/link";

import { LogoMark } from "@/components/logo";

export default function NotFound() {
  return (
    <main className="bg-grid flex flex-1 items-center justify-center px-4 py-24">
      <section className="flex max-w-md flex-col items-center gap-4 rounded-xl border bg-card p-8 text-center">
        <LogoMark className="size-10" />
        <p className="font-mono text-xs text-muted-foreground">404 · no matching recording</p>
        <h1 className="text-xl font-semibold">Not found</h1>
        <p className="text-sm text-muted-foreground">
          There is no page, project or run at this address. It may have been deleted, or the
          id in the URL is incomplete.
        </p>
        <div className="flex gap-3 text-sm">
          <Link href="/projects" className="rounded-md border px-3 py-1.5 hover:bg-muted">
            Back to projects
          </Link>
          <Link href="/" className="rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground">
            Home
          </Link>
        </div>
      </section>
    </main>
  );
}
