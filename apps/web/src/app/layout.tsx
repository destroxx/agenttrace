import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import {
  HealthIndicator,
  HealthIndicatorFallback,
} from "@/components/health-indicator";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AgentTrace",
  description: "Record-and-replay regression testing for AI agents.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header className="border-b">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <nav className="flex items-center gap-6 text-sm">
              <Link href="/" className="font-semibold tracking-tight">
                AgentTrace
              </Link>
              <Link href="/" className="text-muted-foreground hover:text-foreground">
                Projects
              </Link>
            </nav>
            <Suspense fallback={<HealthIndicatorFallback />}>
              <HealthIndicator />
            </Suspense>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
