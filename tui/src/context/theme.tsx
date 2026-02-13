import { createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";

export interface ThemeColors {
  primary: string;
  secondary: string;
  accent: string;

  error: string;
  warning: string;
  success: string;
  info: string;

  text: string;
  textMuted: string;
  textDim: string;
  selectedText: string;

  background: string;
  backgroundPanel: string;
  backgroundElement: string;
  backgroundHighlight: string;
  backgroundOverlay: string;

  border: string;
  borderActive: string;
  borderSubtle: string;

  recording: string;
  transcribing: string;
  ready: string;
}

export interface Theme {
  name: string;
  colors: ThemeColors;
}

const opencodeDark: Theme = {
  name: "opencode-dark",
  colors: {
    primary: "#fab283",
    secondary: "#5c9cf5",
    accent: "#9d7cd8",

    error: "#e06c75",
    warning: "#f5a742",
    success: "#7fd88f",
    info: "#56b6c2",

    text: "#eeeeee",
    textMuted: "#808080",
    textDim: "#606060",
    selectedText: "#0a0a0a",

    background: "#0a0a0a",
    backgroundPanel: "#141414",
    backgroundElement: "#1e1e1e",
    backgroundHighlight: "#282828",
    backgroundOverlay: "#000000",

    border: "#484848",
    borderActive: "#606060",
    borderSubtle: "#323232",

    recording: "#e06c75",
    transcribing: "#f5a742",
    ready: "#7fd88f",
  },
};

export const themes: Record<string, Theme> = {
  "opencode-dark": opencodeDark,
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
  const [currentTheme, setCurrentTheme] = createSignal<Theme>(opencodeDark);

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
