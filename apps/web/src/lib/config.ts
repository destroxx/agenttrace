/**
 * Client-visible configuration.
 *
 * `NEXT_PUBLIC_*` values are inlined into the browser bundle at build time, so
 * only non-secret values belong here.
 */

const DEFAULT_API_URL = "http://localhost:8000";

export const apiBaseUrl: string = (
  process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL
).replace(/\/$/, "");
