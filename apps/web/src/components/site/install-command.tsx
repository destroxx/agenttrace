"use client";

/**
 * The SDK's install line, with a button that copies it.
 *
 * The only client JavaScript in the section: copying needs the clipboard API.
 * Without it (an insecure context, a denied permission) the command is still
 * plain, selectable text, so nothing is lost when the copy fails.
 */

import { useState } from "react";

import { buttonClasses } from "@/components/brand/primitives";

export function InstallCommand({
  command,
  alternative,
  href,
}: {
  command: string;
  alternative?: string;
  href?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-md border bg-code p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-5">
      <div className="flex min-w-0 flex-col gap-1.5">
        <code className="overflow-x-auto text-[13px] leading-6 whitespace-nowrap">
          <span className="text-muted-foreground/70">$ </span>
          {command}
        </code>
        {alternative ? (
          <p className="text-xs text-muted-foreground">
            or <code className="text-foreground">{alternative}</code>
            {href ? (
              <>
                {" · "}
                <a
                  href={href}
                  className="underline decoration-line-strong underline-offset-4 hover:text-signal"
                >
                  on PyPI
                </a>
              </>
            ) : null}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={copy}
        className={`${buttonClasses("secondary")} shrink-0 self-start sm:self-auto`}
        aria-label={`Copy: ${command}`}
      >
        <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
      </button>
    </div>
  );
}
