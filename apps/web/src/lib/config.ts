/**
 * Client-visible configuration.
 *
 * `NEXT_PUBLIC_*` values are inlined into the browser bundle at build time, so
 * only non-secret values belong here.
 */

const DEFAULT_API_URL = "http://localhost:8000";
const DEFAULT_SITE_URL = "http://localhost:3000";

/**
 * Where the browser reaches the API. Empty on Vercel, where the API is served
 * from the same origin (see next.config.ts), so requests go to relative paths
 * like `/health` and every preview calls its own deployment's API.
 */
export const apiBaseUrl: string = (
  process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL
).replace(/\/$/, "");

/**
 * Where this code reaches the API from wherever it is running.
 *
 * On the server a relative URL means nothing, and the public URL of a preview
 * sits behind Vercel's deployment protection. So server code prefers the
 * private service binding Vercel injects at runtime (`vercel.json`), which
 * points at the API of this same deployment and skips the public edge. In the
 * browser, and locally where there is no binding, it is `apiBaseUrl`.
 */
export function apiBase(): string {
  if (typeof window === "undefined") {
    const internal = process.env.AGENTTRACE_API_INTERNAL_URL;
    if (internal) return internal.replace(/\/$/, "");
  }
  return apiBaseUrl;
}

/**
 * The site's own public origin. Link previews need absolute URLs for their
 * images, and `metadataBase` turns the relative ones Next generates into
 * those. Localhost is only right for local development.
 */
export const siteUrl: string = process.env.NEXT_PUBLIC_SITE_URL ?? DEFAULT_SITE_URL;

/**
 * The API's address as a person would type it, for text the page displays:
 * a curl command with a relative URL cannot be pasted into a terminal.
 */
export const publicApiUrl: string = apiBaseUrl || siteUrl.replace(/\/$/, "");
