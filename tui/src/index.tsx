import { render } from "@opentui/solid";
import { App } from "./app";
import { handleSigint } from "./util/interrupt";

let terminalRestored = false;

/**
 * Restore the terminal to a normal state for shutdown.
 *
 * This function is idempotent and does nothing after the first call. It attempts to disable stdin raw mode and reset terminal modes (mouse tracking, cursor visibility, and text style); any errors encountered during these attempts are ignored.
 */
function restoreTerminalState() {
  if (terminalRestored) return;
  terminalRestored = true;

  try {
    if (process.stdin.isTTY && "setRawMode" in process.stdin) {
      (process.stdin as NodeJS.ReadStream).setRawMode(false);
    }
  } catch {
    // Ignore raw mode reset errors during shutdown
  }

  try {
    // Disable common mouse tracking modes and restore cursor/style.
    process.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m");
  } catch {
    // Ignore terminal write errors during shutdown
  }
}

const captureSeconds = Number.parseFloat(
  process.env.WHISPER_LOCAL_TUI_CAPTURE_SECONDS ?? "",
);
const captureMode = Number.isFinite(captureSeconds) && captureSeconds > 0;

if (!captureMode) {
  process.on("exit", restoreTerminalState);
  process.on("SIGINT", () => {
    if (handleSigint()) {
      return;
    }
    restoreTerminalState();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    restoreTerminalState();
    process.exit(0);
  });
}

// Parse command line arguments for host/port
const args = process.argv.slice(2);
let host = "localhost";
let port = 7878;

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--host" && args[i + 1]) {
    host = args[i + 1];
    i++;
  } else if (args[i] === "--port" && args[i + 1]) {
    port = parseInt(args[i + 1], 10);
    i++;
  }
}

if (captureMode) {
  setTimeout(() => {
    // Capture mode intentionally exits abruptly so the final captured frame
    // remains the rendered UI instead of terminal-reset cleanup output.
    process.kill(process.pid, "SIGKILL");
  }, captureSeconds * 1000);
}

// Render the app
render(() => <App host={host} port={port} />);