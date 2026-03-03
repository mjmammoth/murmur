import { type JSX } from "solid-js";
import { useTheme } from "../context/theme";
import { BrandTitle } from "./brand-title";

interface HeaderProps {
  readonly onQuitClick?: () => void;
}

/**
 * Render the application header with the brand title on the left and an escape/quit hint on the right.
 *
 * The right-side hint invokes the provided callback when clicked (mouse-up).
 *
 * @param props.onQuitClick - Optional callback invoked on mouse-up of the exit hint.
 * @returns The header JSX element containing the brand title and an "esc/q" exit hint.
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
