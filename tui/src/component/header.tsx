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

interface ToggleHintProps {
  keyChar: string;
  label: string;
  active: boolean;
}

/**
 * Render a compact keyboard hint showing a label with one character highlighted and its enabled state.
 *
 * @param props.keyChar - Single character to highlight within `label` (match is case-insensitive). If not found, `keyChar` is shown after the label.
 * @param props.label - Text label containing the key to highlight.
 * @param props.active - Feature state; determines whether the indicator displays "on" (active) or "off" (inactive).
 * @returns A JSX element that displays the label with the highlighted key followed by ": on" or ": off".
 */
function ToggleHint(props: ToggleHintProps): JSX.Element {
  const { colors } = useTheme();
  const idx = Math.max(0, props.label.toLowerCase().indexOf(props.keyChar.toLowerCase()));
  const before = props.label.slice(0, idx);
  const key = props.label[idx] ?? props.keyChar;
  const after = props.label.slice(idx + 1);

  return (
    <text>
      <span style={{ fg: colors().textDim }}>{before}</span>
      <span style={{ fg: colors().accent, bold: true }}>{key}</span>
      <span style={{ fg: colors().textDim }}>{after}</span>
      <span style={{ fg: colors().textMuted }}>:</span>
      <span style={{ fg: props.active ? colors().success : colors().textDim }}>
        {props.active ? " on" : " off"}
      </span>
    </text>
  );
}

/**
 * Render the application header with an animated brand color strip and configuration toggles.
 *
 * The left side displays " whisper.local " as a sequence of colored tiles whose background
 * interpolates between the theme's brandStart and brandEnd based on distance from a peak
 * near the dot. The right side shows toggle hints for noise suppression (`n`), VAD (`v`),
 * auto copy (`a`), and auto paste (`p`) reflecting the current configuration signals.
 *
 * @returns A JSX element containing the header UI: the animated brand strip on the left and the toggle hints on the right.
 */
export function Header(): JSX.Element {
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
          gap={2}
          alignItems="center"
          flexShrink={0}
        >
          <ToggleHint keyChar="n" label="noise suppression" active={config.noiseEnabled()} />
          <ToggleHint keyChar="v" label="vad" active={config.vadEnabled()} />
          <ToggleHint keyChar="a" label="auto copy" active={config.autoCopy()} />
          <ToggleHint keyChar="p" label="auto paste" active={config.autoPaste()} />
        </box>
      </box>
    </box>
  );
}
