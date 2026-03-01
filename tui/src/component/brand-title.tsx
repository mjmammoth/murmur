import { For, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { lerpColor } from "../util/color";

const TITLE = "murmur";

/**
 * Renders the branded title "murmur" as a horizontal row of character tiles.
 *
 * Each character (with leading/trailing padding) is placed in its own colored box; background colors are interpolated between the theme's `brandStart` and `brandEnd` and weighted so the gradient peaks at the visual center of the title strip.
 *
 * @returns A JSX element containing the title rendered as horizontally arranged boxes with per-character background colors forming a centered gradient.
 */
export function BrandTitle(): JSX.Element {
  const { colors } = useTheme();
  const titleChars = TITLE.split("");
  const titleStripChars = [" ", ...titleChars, " "];
  const titleLastIndex = Math.max(1, titleStripChars.length - 1);
  const peakIndex = Math.floor(titleLastIndex / 2);
  const maxDistanceFromPeak = Math.max(1, Math.max(peakIndex, titleLastIndex - peakIndex));

  return (
    <box flexDirection="row" flexShrink={0}>
      <For each={titleStripChars}>
        {(ch, i) => {
          const distanceFromPeak = Math.abs(i() - peakIndex);
          const normalizedDistance = Math.min(1, distanceFromPeak / maxDistanceFromPeak);
          const easedDistance = Math.pow(normalizedDistance, 1.35);
          // Keep center dark and limit edge lightness for a softer gradient.
          const intensity = 1 - 0.45 * easedDistance;
          const bgColor = lerpColor(colors().brandStart, colors().brandEnd, intensity);
          return (
            <box backgroundColor={bgColor}>
              <text>
                <span style={{ fg: colors().background, bold: true }}>{ch}</span>
              </text>
            </box>
          );
        }}
      </For>
    </box>
  );
}
