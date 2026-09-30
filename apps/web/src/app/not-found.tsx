import { ButtonLink, Display, Micro, Panel } from "@/components/brand/primitives";

/**
 * The one 404 for the whole app. Inside the dashboard it renders under the
 * dashboard's header; for an unknown URL it stands alone, so it brings its own
 * `.dark` wrapper to match either way.
 */
export default function NotFound() {
  return (
    <div data-surface="app" className="dark bg-grid flex flex-1 items-center justify-center bg-background px-5 py-24 font-mono text-foreground">
      <Panel className="w-full max-w-lg">
        <section className="flex flex-col gap-5 p-6 sm:p-8">
          <Micro tone="brand">404 · no matching recording</Micro>
          <Display as="h1" className="text-4xl md:text-5xl">
            Not found
          </Display>
          <p className="text-[13px] leading-6 text-muted-foreground">
            There is no page, project or run at this address. It may have been deleted, or the
            id in the URL is incomplete.
          </p>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href="/projects">Back to projects</ButtonLink>
            <ButtonLink href="/" variant="secondary">
              Home
            </ButtonLink>
          </div>
        </section>
      </Panel>
    </div>
  );
}
