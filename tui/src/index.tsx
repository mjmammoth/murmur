import { render } from "@opentui/solid";
import { App } from "./app";
import { handleSigint } from "./util/interrupt";

let terminalRestored = false;

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

// Render the app
render(() => <App host={host} port={port} />);
