import type { NextConfig } from "next";

/**
 * Build-time defaults for deployments on Vercel, where `VERCEL=1`.
 *
 * The API is a service of the same deployment (`vercel.json` at the repo
 * root), so the browser reaches it on the same origin: an empty base URL
 * makes its requests relative, and each preview talks to its own API rather
 * than production's. Link previews need an absolute site URL; Vercel provides
 * the production domain. An explicit NEXT_PUBLIC_* variable still wins, and
 * off Vercel nothing here applies, so local development keeps its
 * localhost defaults (src/lib/config.ts).
 */
function vercelDefaults(): Record<string, string> {
  if (process.env.VERCEL !== "1") return {};
  const env: Record<string, string> = {};
  if (process.env.NEXT_PUBLIC_API_URL === undefined) {
    env.NEXT_PUBLIC_API_URL = "";
  }
  const productionHost = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (process.env.NEXT_PUBLIC_SITE_URL === undefined && productionHost) {
    env.NEXT_PUBLIC_SITE_URL = `https://${productionHost}`;
  }
  return env;
}

const nextConfig: NextConfig = {
  env: vercelDefaults(),
};

export default nextConfig;
