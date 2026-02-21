import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { BrandTitle } from "./brand-title";

interface HeaderProps {
  onQuitClick?: () => void;
}

/**
 * Render the application header with an animated brand color strip and a quit hint.
 *
 * The left side displays " whisper.local " as a sequence of colored tiles whose background
 * interpolates between the theme's brandStart and brandEnd based on distance from a peak
 * near the dot. The right side shows the `esc/q` exit hint.
 *
 * @returns A JSX element containing the header UI: the animated brand strip on the left and the exit hint on the right.
 */
export function Header(props: HeaderProps): JSX.Element {
  const { colors } = useTheme();

  return (
    <box
      paddingX={2}
      paddingTop={0}
      paddingBottom={0}
      flexShrink={0}
    >
      <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
        <BrandTitle />
        <box
          justifyContent="flex-end"
          flexDirection="row"
          alignItems="center"
          flexShrink={0}
          onMouseUp={props.onQuitClick}
        >
          <box backgroundColor={colors().error} paddingX={1}>
            <text>
              <span style={{ fg: colors().selectedText }}>esc/q</span>
            </text>
          </box>
          <text>
            <span style={{ fg: colors().textMuted }}> exit</span>
          </text>
        </box>
      </box>
    </box>
  );
}
