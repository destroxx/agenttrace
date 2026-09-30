"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";

import { buttonClasses, Display, Micro } from "@/components/brand/primitives";

/**
 * The last resort for a page that threw while rendering.
 *
 * API failures do not land here — pages render those themselves — so this
 * is a bug in the dashboard, and says so rather than blaming the API.
 */
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <section className="flex max-w-3xl flex-col gap-4" role="alert">
      <Micro tone="fail">render error</Micro>
      <Display className="text-3xl md:text-4xl">This page failed to render</Display>
      <p className="text-[13px] leading-6 text-muted-foreground">
        {error.message}
        {error.digest ? ` (digest ${error.digest}, see the server log)` : null}
      </p>
      <button type="button" className={`${buttonClasses("primary")} self-start`} onClick={() => retry()}>
        Try again
      </button>
    </section>
  );
}
