import { ErrorBoundary, type JSX } from "solid-js";
import { ThemeContextProvider, useTheme } from "./context/theme";
import { BackendContextProvider } from "./context/backend";
import { ConfigContextProvider } from "./context/config";
import { TranscriberContextProvider } from "./context/transcriber";
import { DialogContextProvider } from "./context/dialog";
import { ToastContextProvider } from "./context/toast";
import { Home } from "./routes/home";

function ErrorFallback(props: { error: Error }): JSX.Element {
  return (
      <box flexDirection="column" padding={2} backgroundColor="#1a0000">
        <text>
          <span style={{ fg: "#ff6b6b" }}>✗ Error: {props.error.message}</span>
        </text>
        <box paddingTop={1}>
          <text>
            <span style={{ fg: "#666666" }}>{props.error.stack}</span>
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
    <ErrorBoundary fallback={(err) => <ErrorFallback error={err} />}>
      <ThemeContextProvider>
        <BackendContextProvider host={props.host} port={props.port}>
          <ConfigContextProvider>
            <TranscriberContextProvider>
              <DialogContextProvider>
                <ToastContextProvider>
                  <Home />
                </ToastContextProvider>
              </DialogContextProvider>
            </TranscriberContextProvider>
          </ConfigContextProvider>
        </BackendContextProvider>
      </ThemeContextProvider>
    </ErrorBoundary>
  );
}
