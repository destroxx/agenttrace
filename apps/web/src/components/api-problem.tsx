/**
 * What a page shows instead of its data when the API did not give it.
 *
 * An unreachable API is expected during local development — the web app is
 * often started first — so it gets an explanation and the live health card,
 * not an error screen. Anything else the API refused is shown with its own
 * message, which is written for people.
 */

import { ApiStatus } from "@/components/api-status";
import { RetryButton } from "@/components/retry-button";
import type { ApiFailure } from "@/lib/api";
import { apiBaseUrl } from "@/lib/config";
import { fetchHealth } from "@/lib/health";

export async function ApiProblem({ failure }: { failure: ApiFailure }) {
  if (failure.kind === "unreachable") {
    const health = await fetchHealth(AbortSignal.timeout(3000));
    return (
      <section className="flex flex-col gap-4" role="alert">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold">Cannot reach the AgentTrace API</h2>
          <p className="text-sm text-muted-foreground">
            The dashboard reads everything from <code>{apiBaseUrl}</code>, and it did not
            answer ({failure.message}). Nothing is wrong with this page: start the API
            and try again.
          </p>
        </div>
        <ApiStatus initialResult={health} />
        <RetryButton label="Reload this page" />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3" role="alert">
      <h2 className="text-lg font-semibold">
        {failure.kind === "not_found"
          ? "Not found"
          : `The API answered ${failure.status}`}
      </h2>
      <p className="text-sm text-muted-foreground">{failure.message}</p>
      <RetryButton />
    </section>
  );
}
