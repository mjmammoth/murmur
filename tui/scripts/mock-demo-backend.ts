interface DemoConfig {
  model: {
    name: string;
    runtime: string;
    device: string;
    compute_type: string;
    path: string | null;
    language: string | null;
  };
  hotkey: {
    mode: "ptt" | "toggle";
    key: string;
  };
  audio: {
    sample_rate: number;
    noise_suppression: { enabled: boolean; level: number };
  };
  vad: {
    enabled: boolean;
    aggressiveness: number;
    min_speech_ms: number;
    max_silence_ms: number;
  };
  output: {
    clipboard: boolean;
    file: { enabled: boolean; path: string };
  };
  bridge: {
    host: string;
    port: number;
  };
  ui: {
    theme: string;
    welcome_shown: boolean;
  };
  auto_copy: boolean;
  auto_paste: boolean;
  auto_revert_clipboard: boolean;
  first_run_setup_required: boolean;
}

interface DemoTranscript {
  timestamp: string;
  text: string;
}

function getArg(name: string, fallback: string): string {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  return process.argv[index + 1] ?? fallback;
}

const port = Number.parseInt(getArg("--port", "8787"), 10);
const theme = getArg("--theme", "dark").toLowerCase();

const transcripts: DemoTranscript[] = [
  {
    timestamp: "08:26:25",
    text: "Create a modern and clean diagram from the below description.",
  },
  {
    timestamp: "08:26:20",
    text: "In GCP, I am trying to get an App Engine deployment of my static docs hosted with a custom domain.",
  },
  {
    timestamp: "06:30:17",
    text: "I added records one by one in Cloud DNS and now I need to confirm the exact mapping strategy.",
  },
  {
    timestamp: "09:18:15",
    text: "Now the domains are certified, but I still need a stable service-level setup for production.",
  },
  {
    timestamp: "09:20:06",
    text: "Check the objective infrastructure repo; I am trying to build to Cloud Run and route traffic safely.",
  },
  {
    timestamp: "09:20:36",
    text: "This specific App Engine service is not the default one and that changes the DNS requirements.",
  },
  {
    timestamp: "09:25:14",
    text: "I already have two A records and two AAAA records configured for the apex and IPv6.",
  },
];

let config: DemoConfig = {
  model: {
    name: "large-v3-turbo",
    runtime: "faster-whisper",
    device: "cpu",
    compute_type: "int8",
    path: null,
    language: null,
  },
  hotkey: {
    mode: "ptt",
    key: "f3",
  },
  audio: {
    sample_rate: 48000,
    noise_suppression: { enabled: true, level: 0.85 },
  },
  vad: {
    enabled: true,
    aggressiveness: 1,
    min_speech_ms: 250,
    max_silence_ms: 700,
  },
  output: {
    clipboard: true,
    file: { enabled: false, path: "" },
  },
  bridge: {
    host: "127.0.0.1",
    port,
  },
  ui: {
    theme,
    welcome_shown: true,
  },
  auto_copy: true,
  auto_paste: true,
  auto_revert_clipboard: true,
  first_run_setup_required: false,
};

const models = [
  {
    name: "small",
    variants: {
      "faster-whisper": {
        runtime: "faster-whisper",
        format: "ct2",
        installed: true,
        path: "~/.cache/whisper-local/small",
      },
      "whisper.cpp": {
        runtime: "whisper.cpp",
        format: "ggml",
        installed: true,
        path: "~/.cache/whisper-local/ggml-small.bin",
      },
    },
  },
  {
    name: "large-v3-turbo",
    variants: {
      "faster-whisper": {
        runtime: "faster-whisper",
        format: "ct2",
        installed: true,
        path: "~/.cache/whisper-local/large-v3-turbo",
      },
      "whisper.cpp": {
        runtime: "whisper.cpp",
        format: "ggml",
        installed: false,
        path: null,
      },
    },
  },
];

function sendJson(ws: ServerWebSocket<unknown>, payload: object) {
  ws.send(JSON.stringify(payload));
}

const server = Bun.serve({
  port,
  fetch(request, serverRef) {
    if (serverRef.upgrade(request)) {
      return;
    }
    return new Response("whisper.local demo backend", { status: 200 });
  },
  websocket: {
    open(ws) {
      sendJson(ws, { type: "status", status: "ready", message: "Ready" });
      sendJson(ws, { type: "config", config });
      sendJson(ws, { type: "models", models });

      transcripts.forEach((entry, index) => {
        setTimeout(() => {
          sendJson(ws, { type: "transcript", timestamp: entry.timestamp, text: entry.text });
        }, 80 * (index + 1));
      });
    },
    message(ws, rawMessage) {
      let data: { type?: string; [key: string]: unknown } | null = null;
      try {
        data = JSON.parse(String(rawMessage)) as { type?: string; [key: string]: unknown };
      } catch {
        return;
      }

      if (!data?.type) return;

      if (data.type === "get_config") {
        sendJson(ws, { type: "config", config });
        return;
      }

      if (data.type === "list_models") {
        sendJson(ws, { type: "models", models });
        return;
      }

      if (data.type === "set_theme") {
        const nextTheme = String(data.theme ?? "").trim().toLowerCase();
        if (nextTheme.length > 0) {
          config = {
            ...config,
            ui: {
              ...config.ui,
              theme: nextTheme,
            },
          };
          sendJson(ws, { type: "config", config });
        }
        return;
      }

      if (data.type === "copy_text") {
        sendJson(ws, {
          type: "toast",
          message: "Copied to clipboard",
          level: "info",
        });
      }
    },
  },
});

console.log(`Demo backend listening on ws://127.0.0.1:${server.port} (theme=${theme})`);
