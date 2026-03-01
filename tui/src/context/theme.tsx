import { createEffect, createMemo, createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";

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

  brandStart: string;
  brandEnd: string;

  errorBackground: string;
  errorText: string;
  errorTrace: string;

  overlayAlpha: number;
}

export interface Theme {
  id: string;
  label: string;
  description: string;
  colors: ThemeColors;
  selectedRow: {
    subtle: string;
    bright: string;
  };
}

const darkTheme: Theme = {
  id: "dark",
  label: "Dark",
  description: "Default dark palette",
  selectedRow: {
    subtle: "#1f3a2f",
    bright: "#2b4d3f",
  },
  colors: {
    primary: "#9d7cd8",
    secondary: "#5c9cf5",
    accent: "#fab283",

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

    brandStart: "#87ceeb",
    brandEnd: "#5c9cf5",

    errorBackground: "#1a0000",
    errorText: "#ff6b6b",
    errorTrace: "#666666",

    overlayAlpha: 0.63,
  },
};

const lightTheme: Theme = {
  id: "light",
  label: "Light",
  description: "High-contrast light mode",
  selectedRow: {
    subtle: "#d7efe3",
    bright: "#b8ddca",
  },
  colors: {
    primary: "#7c3aed",
    secondary: "#2563eb",
    accent: "#9a4f16",

    error: "#b42318",
    warning: "#b54708",
    success: "#067647",
    info: "#0e7490",

    text: "#1f2937",
    textMuted: "#6b7280",
    textDim: "#94a3b8",
    selectedText: "#ffffff",

    background: "#f8fafc",
    backgroundPanel: "#ffffff",
    backgroundElement: "#f1f5f9",
    backgroundHighlight: "#e2e8f0",
    backgroundOverlay: "#0f172a",

    border: "#cbd5e1",
    borderActive: "#94a3b8",
    borderSubtle: "#e2e8f0",

    recording: "#dc2626",
    transcribing: "#d97706",
    ready: "#16a34a",

    brandStart: "#0ea5e9",
    brandEnd: "#2563eb",

    errorBackground: "#fee2e2",
    errorText: "#b91c1c",
    errorTrace: "#7f1d1d",

    overlayAlpha: 0.24,
  },
};

const catppuccinMochaTheme: Theme = {
  id: "catppuccin-mocha",
  label: "Catppuccin Mocha",
  description: "Pastel dark palette",
  selectedRow: {
    subtle: "#243a31",
    bright: "#315146",
  },
  colors: {
    primary: "#cba6f7",
    secondary: "#89b4fa",
    accent: "#fab387",

    error: "#f38ba8",
    warning: "#f9e2af",
    success: "#a6e3a1",
    info: "#89dceb",

    text: "#cdd6f4",
    textMuted: "#a6adc8",
    textDim: "#6c7086",
    selectedText: "#11111b",

    background: "#11111b",
    backgroundPanel: "#1e1e2e",
    backgroundElement: "#313244",
    backgroundHighlight: "#45475a",
    backgroundOverlay: "#11111b",

    border: "#585b70",
    borderActive: "#7f849c",
    borderSubtle: "#45475a",

    recording: "#f38ba8",
    transcribing: "#f9e2af",
    ready: "#a6e3a1",

    brandStart: "#74c7ec",
    brandEnd: "#89b4fa",

    errorBackground: "#2b1a22",
    errorText: "#f38ba8",
    errorTrace: "#f5c2e7",

    overlayAlpha: 0.58,
  },
};

const catppuccinLatteTheme: Theme = {
  id: "catppuccin-latte",
  label: "Catppuccin Latte",
  description: "Pastel light palette",
  selectedRow: {
    subtle: "#cadfce",
    bright: "#afd0ba",
  },
  colors: {
    primary: "#8839ef",
    secondary: "#1e66f5",
    accent: "#d17b49",

    error: "#d20f39",
    warning: "#df8e1d",
    success: "#40a02b",
    info: "#04a5e5",

    text: "#4c4f69",
    textMuted: "#6c6f85",
    textDim: "#8c8fa1",
    selectedText: "#eff1f5",

    background: "#eff1f5",
    backgroundPanel: "#e6e9ef",
    backgroundElement: "#ccd0da",
    backgroundHighlight: "#bcc0cc",
    backgroundOverlay: "#4c4f69",

    border: "#acb0be",
    borderActive: "#9ca0b0",
    borderSubtle: "#ccd0da",

    recording: "#d20f39",
    transcribing: "#df8e1d",
    ready: "#40a02b",

    brandStart: "#179299",
    brandEnd: "#1e66f5",

    errorBackground: "#f4d9df",
    errorText: "#d20f39",
    errorTrace: "#5c5f77",

    overlayAlpha: 0.25,
  },
};

const DEFAULT_THEME_ID = "dark";

const themeList: Theme[] = [
  darkTheme,
  lightTheme,
  catppuccinMochaTheme,
  catppuccinLatteTheme,
];

export const themes: Record<string, Theme> = Object.fromEntries(
  themeList.map((theme) => [theme.id, theme]),
) as Record<string, Theme>;

const themeAliases: Record<string, string> = {
  "opencode-dark": DEFAULT_THEME_ID,
  default: DEFAULT_THEME_ID,
};

function normalizeThemeId(name: string | null | undefined): string | null {
  if (!name) return null;
  const normalized = name.trim().toLowerCase();
  if (!normalized) return null;
  if (themes[normalized]) return normalized;
  const alias = themeAliases[normalized];
  return alias && themes[alias] ? alias : null;
}

export interface ThemeContextValue {
  theme: Accessor<Theme>;
  themeId: Accessor<string>;
  colors: Accessor<ThemeColors>;
  setTheme: (name: string) => void;
  persistTheme: (name?: string) => void;
  availableThemes: Theme[];
}

const [ThemeProvider, useTheme] = createContextHelper<ThemeContextValue>("Theme");
export { useTheme };

export function ThemeContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();
  const [currentThemeId, setCurrentThemeId] = createSignal<string>(DEFAULT_THEME_ID);
  const theme = createMemo(() => themes[currentThemeId()] ?? themes[DEFAULT_THEME_ID]);

  const colors = () => theme().colors;

  function setTheme(name: string) {
    const resolved = normalizeThemeId(name);
    if (!resolved) return;
    setCurrentThemeId(resolved);
  }

  function persistTheme(name?: string) {
    const resolved = normalizeThemeId(name ?? currentThemeId());
    if (!resolved) return;
    setCurrentThemeId(resolved);
    backend.send({ type: "set_theme", theme: resolved });
  }

  createEffect(() => {
    const configuredTheme = backend.config()?.ui?.theme;
    const resolved = normalizeThemeId(configuredTheme);
    if (!resolved) return;
    setCurrentThemeId((previous) => (previous === resolved ? previous : resolved));
  });

  const value: ThemeContextValue = {
    theme,
    themeId: currentThemeId,
    colors,
    setTheme,
    persistTheme,
    availableThemes: themeList,
  };

  return <ThemeProvider value={value}>{props.children}</ThemeProvider>;
}
