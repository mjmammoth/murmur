import { createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";

export interface ThemeColors {
  // Primary colors
  primary: string;
  secondary: string;
  accent: string;

  // Status colors
  error: string;
  warning: string;
  success: string;
  info: string;

  // Text colors
  text: string;
  textMuted: string;
  textDim: string;

  // Background colors
  background: string;
  backgroundPanel: string;
  backgroundElement: string;
  backgroundHighlight: string;

  // Border colors
  border: string;
  borderActive: string;
  borderSubtle: string;

  // Recording states
  recording: string;
  transcribing: string;
  ready: string;
}

export interface Theme {
  name: string;
  colors: ThemeColors;
}

// Whisper-inspired dark theme
const whisperDark: Theme = {
  name: "whisper-dark",
  colors: {
    primary: "#7C3AED",      // Purple - main brand
    secondary: "#6366F1",    // Indigo
    accent: "#22D3EE",       // Cyan

    error: "#EF4444",
    warning: "#F59E0B",
    success: "#10B981",
    info: "#3B82F6",

    text: "#F9FAFB",
    textMuted: "#9CA3AF",
    textDim: "#6B7280",

    background: "#111827",
    backgroundPanel: "#1F2937",
    backgroundElement: "#374151",
    backgroundHighlight: "#4B5563",

    border: "#374151",
    borderActive: "#7C3AED",
    borderSubtle: "#1F2937",

    recording: "#EF4444",
    transcribing: "#F59E0B",
    ready: "#10B981",
  },
};

// Minimal dark theme
const minimalDark: Theme = {
  name: "minimal-dark",
  colors: {
    primary: "#FFFFFF",
    secondary: "#A1A1AA",
    accent: "#FAFAFA",

    error: "#F87171",
    warning: "#FBBF24",
    success: "#34D399",
    info: "#60A5FA",

    text: "#FAFAFA",
    textMuted: "#A1A1AA",
    textDim: "#71717A",

    background: "#09090B",
    backgroundPanel: "#18181B",
    backgroundElement: "#27272A",
    backgroundHighlight: "#3F3F46",

    border: "#27272A",
    borderActive: "#FAFAFA",
    borderSubtle: "#18181B",

    recording: "#F87171",
    transcribing: "#FBBF24",
    ready: "#34D399",
  },
};

// Dracula theme
const dracula: Theme = {
  name: "dracula",
  colors: {
    primary: "#BD93F9",
    secondary: "#FF79C6",
    accent: "#8BE9FD",

    error: "#FF5555",
    warning: "#FFB86C",
    success: "#50FA7B",
    info: "#8BE9FD",

    text: "#F8F8F2",
    textMuted: "#6272A4",
    textDim: "#44475A",

    background: "#282A36",
    backgroundPanel: "#21222C",
    backgroundElement: "#44475A",
    backgroundHighlight: "#6272A4",

    border: "#44475A",
    borderActive: "#BD93F9",
    borderSubtle: "#21222C",

    recording: "#FF5555",
    transcribing: "#FFB86C",
    ready: "#50FA7B",
  },
};

export const themes: Record<string, Theme> = {
  "whisper-dark": whisperDark,
  "minimal-dark": minimalDark,
  dracula: dracula,
};

export interface ThemeContextValue {
  theme: Accessor<Theme>;
  colors: Accessor<ThemeColors>;
  setTheme: (name: string) => void;
  availableThemes: string[];
}

const [ThemeProvider, useTheme] = createContextHelper<ThemeContextValue>("Theme");
export { useTheme };

export function ThemeContextProvider(props: { children: JSX.Element }): JSX.Element {
  const [currentTheme, setCurrentTheme] = createSignal<Theme>(whisperDark);

  const colors = () => currentTheme().colors;

  function setTheme(name: string) {
    const theme = themes[name];
    if (theme) {
      setCurrentTheme(theme);
    }
  }

  const value: ThemeContextValue = {
    theme: currentTheme,
    colors,
    setTheme,
    availableThemes: Object.keys(themes),
  };

  return <ThemeProvider value={value}>{props.children}</ThemeProvider>;
}
