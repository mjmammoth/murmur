import { ErrorBoundary, type JSX } from "solid-js";
import { ThemeContextProvider, useTheme } from "./context/theme";
import { BackendContextProvider } from "./context/backend";
import { ConfigContextProvider } from "./context/config";
import { TranscriberContextProvider } from "./context/transcriber";
import { DialogContextProvider } from "./context/dialog";
import { ToastContextProvider } from "./context/toast";
import { Home } from "./routes/home";

function ErrorFallback(props: { error: Error }): JSX.Element {
  const { colors } = useTheme();

  return (
    <box flexDirection="column" padding={2} backgroundColor={colors().errorBackground}>
      <text>
        <span style={{ fg: colors().errorText }}>✗ Error: {props.error.message}</span>
      </text>
      <box paddingTop={1}>
        <text>
          <span style={{ fg: colors().errorTrace }}>{props.error.stack}</span>
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
