import { type JSX, For } from "solid-js";
import { useTheme } from "../context/theme";
import { useConfig } from "../context/config";

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

export function Header(): JSX.Element {
  const { colors } = useTheme();
  const config = useConfig();

  return (
    <box
      paddingX={2}
      paddingTop={0}
      paddingBottom={0}
      flexShrink={0}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
        <text>
          <For each={"whisper.local".split("")}>
            {(ch, i) => {
              const peak = 7; // the '.' in whisper.local
              const t = i() <= peak ? i() / peak : (12 - i()) / (12 - peak);
              return (
                <span style={{
                  fg: lerpColor("#87CEEB", colors().secondary, t),
                  bold: true,
                }}>
                  {ch}
                </span>
              );
            }}
          </For>
        </text>

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
        </box>
      </box>
    </box>
  );
}
