import { ErrorBoundary, type JSX } from "solid-js";
import { ThemeContextProvider, useTheme } from "./context/theme";
import { BackendContextProvider } from "./context/backend";
import { ConfigContextProvider } from "./context/config";
import { TranscriberContextProvider } from "./context/transcriber";
import { DialogContextProvider } from "./context/dialog";
import { ToastContextProvider } from "./context/toast";
import { Home } from "./routes/home";

function ErrorFallback(props: { error: Error }): JSX.Element {
  let themeColors: ReturnType<ReturnType<typeof useTheme>["colors"]> | null = null;
  try {
    const { colors } = useTheme();
    themeColors = colors();
  } catch {
    // Theme context unavailable — use hardcoded fallback colors
  }

  const bg = themeColors?.errorBackground ?? "#1a0000";
  const fg = themeColors?.errorText ?? "#ff4444";
  const trace = themeColors?.errorTrace ?? "#888888";

  return (
    <box flexDirection="column" padding={2} backgroundColor={bg}>
      <text>
        <span style={{ fg }}>Error: {props.error.message}</span>
      </text>
      <box paddingTop={1}>
        <text>
          <span style={{ fg: trace }}>{props.error.stack}</span>
        </text>
      </box>
    </box>
  );
}

export interface AppProps {
  host?: string;
  port?: number;
}

export function App(props: AppProps): JSX.Element {
  return (
    <BackendContextProvider host={props.host} port={props.port}>
      <ThemeContextProvider>
        <ErrorBoundary fallback={(err) => <ErrorFallback error={err} />}>
          <ConfigContextProvider>
            <TranscriberContextProvider>
              <DialogContextProvider>
                <ToastContextProvider>
                  <Home />
                </ToastContextProvider>
              </DialogContextProvider>
            </TranscriberContextProvider>
          </ConfigContextProvider>
        </ErrorBoundary>
      </ThemeContextProvider>
    </BackendContextProvider>
  );
}
