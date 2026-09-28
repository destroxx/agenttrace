/**
 * The landing page's sections in page order. Each section's timecode is its
 * position here, and the nav reads the same list, so a nav number always
 * names the section it links to.
 */

export const SECTIONS = [
  { id: "regressions", label: "regressions", nav: true },
  { id: "how", label: "how it works", nav: true },
  { id: "demo", label: "replay demo", nav: true },
  { id: "dashboard", label: "dashboard", nav: false },
  { id: "sdk", label: "python sdk", nav: false },
  { id: "ci", label: "suites and ci", nav: true },
  { id: "proof", label: "proof", nav: true },
  { id: "quickstart", label: "quickstart", nav: false },
  { id: "faq", label: "faq", nav: true },
] as const;

export type SectionId = (typeof SECTIONS)[number]["id"];

/** 1-based position of a section, as shown in its timecode and the nav. */
export function sectionIndex(id: SectionId): number {
  return SECTIONS.findIndex((section) => section.id === id) + 1;
}

export function sectionLabel(id: SectionId): string {
  return SECTIONS.find((section) => section.id === id)!.label;
}

export const NAV_ITEMS = SECTIONS.filter((section) => section.nav).map((section) => ({
  href: `/#${section.id}`,
  label: section.label,
  index: sectionIndex(section.id),
}));
