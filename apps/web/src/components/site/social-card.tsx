/**
 * The link-preview card for the landing page, shared by `opengraph-image`
 * and `twitter-image` so both previews are the same picture.
 *
 * `ImageResponse` cannot use the page's CSS fonts, and reads only ttf, otf or
 * woff. Google Fonts serves ttf to a request without a browser user agent, and
 * the `text=` parameter subsets the font to the characters drawn, which keeps
 * the image well under its bundle limit. The fetch runs once, when the image
 * is generated at build time; if it fails, the card falls back to the
 * renderer's built-in font rather than failing the build.
 */

import { ImageResponse } from "next/og";

export const SOCIAL_TITLE = "AgentTrace";
export const SOCIAL_TAGLINE = "Test every agent change against a real run.";
export const SOCIAL_DESCRIPTION =
  "Record a real run of your AI agent, replay the next change against it without calling a single real tool, and get a PASS or FAIL you can gate a release on.";

export const socialImageSize = { width: 1200, height: 630 };
export const socialImageAlt = `${SOCIAL_TITLE}: ${SOCIAL_TAGLINE}`;

// The landing page's dark palette (globals.css, `.dark`).
const COLOR = {
  background: "#0d0c0a",
  band: "#12110e",
  foreground: "#ece5d3",
  muted: "#a39d8f",
  line: "#3b372f",
  signal: "#ff8a3d",
  fail: "#ff5d5d",
};

const FOOTER = "record · replay · compare";

async function googleFont(family: string, weight: number, text: string): Promise<ArrayBuffer | null> {
  try {
    const css = await (
      await fetch(
        `https://fonts.googleapis.com/css2?family=${family.replace(/ /g, "+")}:wght@${weight}&text=${encodeURIComponent(text)}`,
      )
    ).text();
    const url = css.match(/src: url\((.+?)\) format\('(?:opentype|truetype)'\)/)?.[1];
    if (!url) return null;
    return await (await fetch(url)).arrayBuffer();
  } catch {
    return null;
  }
}

// One call of the recorded support-agent run per bar, as on the hero's tape:
// [start, end, lane] in sequence numbers out of 13, the fifth one skipped.
const SPANS: [number, number, number][] = [
  [1, 2, 0],
  [3, 5, 0],
  [4, 6, 1],
  [7, 8, 0],
  [9, 10, 0],
  [11, 12, 0],
];

export async function renderSocialCard(): Promise<ImageResponse> {
  const [display, mono] = await Promise.all([
    googleFont("Doto", 900, `${SOCIAL_TITLE.toLowerCase()}${SOCIAL_TAGLINE}`),
    googleFont("JetBrains Mono", 400, FOOTER),
  ]);
  const fonts = [
    ...(display ? [{ name: "Doto", data: display, weight: 900 as const, style: "normal" as const }] : []),
    ...(mono ? [{ name: "JetBrains Mono", data: mono, weight: 400 as const, style: "normal" as const }] : []),
  ];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "64px 72px",
          background: COLOR.background,
          color: COLOR.foreground,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 22, height: 22, borderRadius: 11, background: COLOR.signal }} />
          <div style={{ fontFamily: "Doto", fontSize: 44, letterSpacing: -1 }}>{SOCIAL_TITLE.toLowerCase()}</div>
        </div>

        <div style={{ fontFamily: "Doto", fontSize: 88, lineHeight: 1.02, letterSpacing: -3, maxWidth: 1000 }}>
          {SOCIAL_TAGLINE}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div style={{ position: "relative", display: "flex", height: 44, borderTop: `2px solid ${COLOR.line}` }}>
            {SPANS.map(([start, end, lane], index) => (
              <div
                key={start}
                style={{
                  position: "absolute",
                  left: `${(start / 13) * 100}%`,
                  width: `${((end - start) / 13) * 100}%`,
                  top: lane ? 26 : 10,
                  height: 10,
                  borderRadius: 5,
                  background: index === 4 ? COLOR.fail : COLOR.muted,
                  opacity: index === 4 ? 0.9 : 0.45,
                }}
              />
            ))}
            <div style={{ position: "absolute", left: "72%", top: -10, width: 3, height: 54, background: COLOR.signal }} />
          </div>
          <div style={{ fontFamily: "JetBrains Mono", fontSize: 26, color: COLOR.muted, letterSpacing: 4 }}>{FOOTER}</div>
        </div>
      </div>
    ),
    { ...socialImageSize, fonts: fonts.length ? fonts : undefined },
  );
}
