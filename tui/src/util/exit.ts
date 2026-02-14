import type { CliRenderer } from "@opentui/core";

export function exitApp(renderer: CliRenderer, exitCode: number = 0): never {
  try {
    renderer.destroy();
  } catch {
    // Ignore renderer teardown errors during exit
  }

  try {
    if (process.stdin.isTTY && "setRawMode" in process.stdin) {
      (process.stdin as NodeJS.ReadStream).setRawMode(false);
    }
  } catch {
    // Ignore raw mode reset errors during exit
  }

  try {
    // Disable common mouse tracking modes and restore cursor/style.
    process.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m");
  } catch {
    // Ignore terminal restore write errors during exit
  }

  process.exit(exitCode);
}
