import { render } from "@opentui/solid";
import { App } from "./app";

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
