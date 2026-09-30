/**
 * What a page shows instead of its data when the API did not give it.
 *
 * An unreachable API is expected during local development — the web app is
 * often started first — so it gets an explanation and the live health card,
 * not an error screen. Anything else the API refused is shown with its own
 * message, which is written for people.
 */

import { ApiStatus } from "@/components/api-status";
import { Display, Micro } from "@/components/brand/primitives";
import { RetryButton } from "@/components/retry-button";
import type { ApiFailure } from "@/lib/api";
import { apiBaseUrl } from "@/lib/config";
import { fetchHealth } from "@/lib/health";

export async function ApiProblem({ failure }: { failure: ApiFailure }) {
  if (failure.kind === "unreachable") {
    const health = await fetchHealth(AbortSignal.timeout(3000));
    return (
      <section className="flex max-w-3xl flex-col gap-6" role="alert">
        <div className="flex flex-col gap-3">
          <Micro tone="fail">api unreachable</Micro>
          <Display className="text-3xl md:text-4xl">Cannot reach the AgentTrace API</Display>
          <p className="max-w-2xl text-[13px] leading-6 text-muted-foreground">
            The dashboard reads everything from <code className="text-foreground">{apiBaseUrl}</code>,
            and it did not answer ({failure.message}). Nothing is wrong with this page: start the
            API and try again.
          </p>
        </div>
        <ApiStatus initialResult={health} />
        <RetryButton label="Reload this page" />
      </section>
    );
  }
  return (
    <section className="flex max-w-3xl flex-col gap-4" role="alert">
      <Micro tone="fail">{failure.kind === "not_found" ? "404" : `http ${failure.status}`}</Micro>
      <Display className="text-3xl md:text-4xl">
        {failure.kind === "not_found"
          ? "Not found"
          : `The API answered ${failure.status}`}
      </Display>
      <p className="text-[13px] leading-6 text-muted-foreground">{failure.message}</p>
      <RetryButton />
    </section>
  );
}
