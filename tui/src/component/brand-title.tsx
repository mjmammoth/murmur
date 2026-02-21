import { For, type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { lerpColor } from "../util/color";

const TITLE = "whisper.local";

/**
 * Renders the branded title "whisper.local" as a horizontal row of character tiles.
 *
 * Each character (with leading/trailing padding) is placed in its own colored box; background colors are interpolated between the theme's `brandStart` and `brandEnd` and weighted so the gradient peaks around the period in the title.
 *
 * @returns A JSX element containing the title rendered as horizontally arranged boxes with per-character background colors forming a gradient centered on the period.
 */
export function BrandTitle(): JSX.Element {
  const { colors } = useTheme();
  const titleChars = TITLE.split("");
  const titleStripChars = [" ", ...titleChars, " "];
  const titleLastIndex = Math.max(1, titleStripChars.length - 1);
  const peakIndex = Math.max(0, TITLE.indexOf(".")) + 1;
  const maxDistanceFromPeak = Math.max(1, Math.max(peakIndex, titleLastIndex - peakIndex));

  return (
    <box flexDirection="row" flexShrink={0}>
      <For each={titleStripChars}>
        {(ch, i) => {
          const distanceFromPeak = Math.abs(i() - peakIndex);
          const baseIntensity = Math.max(0, 1 - distanceFromPeak / maxDistanceFromPeak);
          const intensity = Math.pow(baseIntensity, 2.1);
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