"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/** The site nav below `md`: a toggle that closes when a link is followed or on Escape. */
export function MobileNav({ items }: { items: { href: string; label: string }[] }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative md:hidden">
      <button
        type="button"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls="site-mobile-nav"
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 cursor-pointer items-center justify-center rounded-md border px-4 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-signal"
      >
        <span aria-hidden>{open ? "close" : "menu"}</span>
      </button>
      {open ? (
        <nav
          id="site-mobile-nav"
          aria-label="Main"
          className="absolute right-0 z-50 mt-2 flex w-60 flex-col rounded-md border bg-code p-2 text-[13px] shadow-2xl"
        >
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="flex min-h-11 items-center px-3 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
