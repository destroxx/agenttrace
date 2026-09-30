"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { buttonClasses } from "@/components/brand/primitives";

/** Re-run the page's server-side fetches without a full browser reload. */
export function RetryButton({ label = "Try again" }: { label?: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  return (
    <button
      type="button"
      className={`${buttonClasses("primary")} self-start`}
      disabled={isPending}
      onClick={() => startTransition(() => router.refresh())}
    >
      {isPending ? "Retrying…" : label}
    </button>
  );
}
