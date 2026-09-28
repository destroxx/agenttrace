"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

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
    <section className="flex flex-col gap-3" role="alert">
      <h2 className="text-lg font-semibold">This page failed to render</h2>
      <p className="text-sm text-muted-foreground">
        {error.message}
        {error.digest ? ` (digest ${error.digest}, see the server log)` : null}
      </p>
      <Button variant="outline" className="self-start" onClick={() => retry()}>
        Try again
      </Button>
    </section>
  );
}
