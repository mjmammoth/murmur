import { type JSX, For } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";

const TITLE = "whisper.local";

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

function lerpColor(from: string, to: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(from);
  const [r2, g2, b2] = hexToRgb(to);
  return rgbToHex(
    Math.round(r1 + (r2 - r1) * t),
    Math.round(g1 + (g2 - g1) * t),
    Math.round(b1 + (b2 - b1) * t),
  );
}

interface HeaderProps {
  onToggleAutoCopy?: () => void;
  onToggleAutoPaste?: () => void;
}

/**
 * Render the application header with an animated brand color strip and configuration toggles.
 *
 * The left side displays " whisper.local " as a sequence of colored tiles whose background
 * interpolates between the theme's brandStart and brandEnd based on distance from a peak
 * near the dot. The right side shows toggle hints for auto copy (`c`) and auto paste (`p`)
 * reflecting the current configuration signals.
 *
 * @returns A JSX element containing the header UI: the animated brand strip on the left and the toggle hints on the right.
 */
export function Header(props: HeaderProps): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();
  const titleChars = TITLE.split("");
  const titleStripChars = [" ", ...titleChars, " "];
  const titleLastIndex = Math.max(1, titleStripChars.length - 1);
  const peakIndex = Math.max(0, TITLE.indexOf(".")) + 1;
  const maxDistanceFromPeak = Math.max(1, Math.max(peakIndex, titleLastIndex - peakIndex));

  return (
    <box
      paddingX={2}
      paddingTop={0}
      paddingBottom={0}
      flexShrink={0}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
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

        <box
          justifyContent="flex-end"
          flexDirection="row"
          alignItems="center"
          flexShrink={0}
        >
          <text>
            <span style={{ fg: colors().textDim }}>auto </span>
          </text>
          <box onMouseUp={() => props.onToggleAutoCopy?.()}>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>c</span>
              <span style={{ fg: config.autoCopy() ? colors().success : colors().textDim }}>opy</span>
            </text>
          </box>
          <text>
            <span style={{ fg: colors().textDim }}> / </span>
          </text>
          <box onMouseUp={() => props.onToggleAutoPaste?.()}>
            <text>
              <span style={{ fg: colors().accent, bold: true }}>p</span>
              <span style={{ fg: config.autoPaste() ? colors().success : colors().textDim }}>aste</span>
            </text>
          </box>
        </box>
      </box>
    </box>
  );
}
