import { renderSocialCard, socialImageAlt, socialImageSize } from "@/components/site/social-card";

// Next reads these exports statically, so each image route declares its own.
export const alt = socialImageAlt;
export const size = socialImageSize;
export const contentType = "image/png";

export default function Image() {
  return renderSocialCard();
}
