import type { Metadata } from "next";
import { Doto, IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";

import { siteUrl } from "@/lib/config";

import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

// Dot-matrix display face for the marketing site's headlines: a tape
// counter's readout, which is what a recording product should look like.
const doto = Doto({
  variable: "--font-doto",
  subsets: ["latin"],
  weight: ["700", "800", "900"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "AgentTrace: regression tests for AI agents",
    template: "%s · AgentTrace",
  },
  description:
    "Record real agent runs, replay them against a new version without calling real tools, and get a PASS/FAIL verdict.",
};

/**
 * Only the document shell. The marketing site and the dashboard bring their
 * own chrome from their route groups, so neither carries the other's header.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${jetbrainsMono.variable} ${doto.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-background text-foreground">{children}</body>
    </html>
  );
}
