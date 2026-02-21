import { createSignal, createEffect, onCleanup, createMemo, Show, type Accessor } from "solid-js";
import type { JSX } from "@opentui/solid";
import { useTheme } from "../context/theme";
import { createColors, createFrames } from "../util/scanner";
import "opentui-spinner/solid";

const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL = 80;

/** Reusable hook that returns the current spinner frame character */
export function useSpinnerFrame(
  frames = BRAILLE_FRAMES,
  interval = SPINNER_INTERVAL
): Accessor<string> {
  const [frameIndex, setFrameIndex] = createSignal(0);

  createEffect(() => {
    const timer = setInterval(() => {
      setFrameIndex((idx) => (idx + 1) % frames.length);
    }, interval);

    onCleanup(() => clearInterval(timer));
  });

  return () => frames[frameIndex()];
}

export interface SpinnerProps {
  label?: string;
  color?: string;
}

/**
 * Render an inline spinner icon with an optional label.
 *
 * @param props.label - Optional text shown after the spinner.
 * @param props.color - Optional foreground color override for the spinner; falls back to the theme accent color when omitted.
 * @returns A JSX element containing the spinner character and, if provided, the label text.
 */
export function Spinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const frame = useSpinnerFrame();
  const spinnerColor = () => props.color ?? colors().accent;

  return (
    <box>
      <text>
        <span style={{ fg: spinnerColor() }}>{frame()}</span>
        {props.label && <span style={{ fg: colors().text }}> {props.label}</span>}
      </text>
    </box>
  );
}

// Dots spinner alternative
const DOTS_FRAMES = ["⋯", "⋱", "⋮", "⋰"];

export function DotsSpinner(props: SpinnerProps): JSX.Element {
  const { colors } = useTheme();
  const frame = useSpinnerFrame(DOTS_FRAMES, 200);

  return (
    <box>
      <text>
        <span style={{ fg: props.color ?? colors().textMuted }}>{frame()}</span>
        {props.label && <span style={{ fg: colors().text }}> {props.label}</span>}
      </text>
    </box>
  );
}

interface ScannerProps {
  active: boolean;
}

/**
 * Renders a scanner-style spinner when active, otherwise displays a dimmed dotted fallback.
 *
 * @param props.active - If `true`, show the animated scanner; if `false`, show a static dimmed dots fallback.
 * @returns A JSX element containing the scanner animation or the fallback text.
 */
export function Scanner(props: ScannerProps): JSX.Element {
  const { colors } = useTheme();

  const scannerDef = createMemo(() => {
    const color = colors().accent;
    return {
      frames: createFrames({
        color,
        width: 8,
        inactiveFactor: 0.6,
        minAlpha: 0.3,
      }),
      color: createColors({
        color,
        width: 8,
        inactiveFactor: 0.6,
        minAlpha: 0.3,
      }),
    };
  });

  return (
    <Show
      when={props.active}
      fallback={
        <text>
          <span style={{ fg: colors().textDim }}>⬝⬝⬝⬝⬝⬝⬝⬝</span>
        </text>
      }
    >
      <spinner frames={scannerDef().frames} color={scannerDef().color} interval={40} />
    </Show>
  );
}