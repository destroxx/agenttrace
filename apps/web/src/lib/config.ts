/**
 * Client-visible configuration.
 *
 * `NEXT_PUBLIC_*` values are inlined into the browser bundle at build time, so
 * only non-secret values belong here.
 */

const DEFAULT_API_URL = "http://localhost:8000";
const DEFAULT_SITE_URL = "http://localhost:3000";

export const apiBaseUrl: string = (
  process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL
).replace(/\/$/, "");

/**
 * The site's own public origin. Link previews need absolute URLs for their
 * images, and `metadataBase` turns the relative ones Next generates into
 * those. Localhost is only right for local development.
 */
export const siteUrl: string = process.env.NEXT_PUBLIC_SITE_URL ?? DEFAULT_SITE_URL;
