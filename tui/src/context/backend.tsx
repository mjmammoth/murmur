import {
  createSignal,
  onCleanup,
  onMount,
  type JSX,
  type Accessor,
} from "solid-js";
import { createContextHelper } from "./helper";
import type { AppConfig, ClientMessage, ServerMessage, ModelInfo, TranscriptEntry, AppStatus, LogEntry } from "../types";

export interface DownloadProgress {
  model: string;
  percent: number;
}

export interface ActiveModelOp {
  type: "pulling" | "removing";
  model: string;
}

export interface BackendContextValue {
  connected: Accessor<boolean>;
  status: Accessor<AppStatus>;
  statusMessage: Accessor<string>;
  statusElapsed: Accessor<number | undefined>;
  config: Accessor<AppConfig | null>;
  models: Accessor<ModelInfo[]>;
  autoCopy: Accessor<boolean>;
  logs: Accessor<LogEntry[]>;
  configFileContent: Accessor<string>;
  configFilePath: Accessor<string>;
  downloadProgress: Accessor<DownloadProgress | null>;
  activeModelOp: Accessor<ActiveModelOp | null>;
  downloadModel: (name: string) => void;
  removeModel: (name: string) => void;
  send: (message: ClientMessage) => void;
  requestConfigFile: () => void;
  onTranscript: (handler: (entry: TranscriptEntry) => void) => void;
  onHotkeyPress: (handler: () => void) => void;
  onHotkeyRelease: (handler: () => void) => void;
  onToast: (handler: (message: string, level: "info" | "error") => void) => void;
}

const [BackendProvider, useBackend] = createContextHelper<BackendContextValue>("Backend");
export { useBackend };

const RECONNECT_DELAY = 2000;

export function BackendContextProvider(props: {
  host?: string;
  port?: number;
  children: JSX.Element;
}): JSX.Element {
  const host = props.host ?? "localhost";
  const port = props.port ?? 7878;

  const [connected, setConnected] = createSignal(false);
  const [status, setStatus] = createSignal<AppStatus>("connecting");
  const [statusMessage, setStatusMessage] = createSignal("Connecting...");
  const [statusElapsed, setStatusElapsed] = createSignal<number | undefined>(undefined);
  const [config, setConfig] = createSignal<AppConfig | null>(null);
  const [models, setModels] = createSignal<ModelInfo[]>([]);
  const [autoCopy, setAutoCopy] = createSignal(false);
  const [logs, setLogs] = createSignal<LogEntry[]>([]);
  const [configFileContent, setConfigFileContent] = createSignal("");
  const [configFilePath, setConfigFilePath] = createSignal("");
  const [downloadProgress, setDownloadProgress] = createSignal<DownloadProgress | null>(null);
  const [activeModelOp, setActiveModelOp] = createSignal<ActiveModelOp | null>(null);
  let logIdCounter = 0;

  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // Event handlers
  const transcriptHandlers: ((entry: TranscriptEntry) => void)[] = [];
  const hotkeyPressHandlers: (() => void)[] = [];
  const hotkeyReleaseHandlers: (() => void)[] = [];
  const toastHandlers: ((message: string, level: "info" | "error") => void)[] = [];

  function connect() {
    if (ws?.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(`ws://${host}:${port}`);

    ws.onopen = () => {
      setConnected(true);
      setStatus("connecting");
      setStatusMessage("Connected");
    };

    ws.onclose = () => {
      setConnected(false);
      setStatus("connecting");
      setStatusMessage("Disconnected. Reconnecting...");
      scheduleReconnect();
    };

    ws.onerror = () => {
      setConnected(false);
      setStatus("error");
      setStatusMessage("Connection error");
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as ServerMessage;
        handleMessage(message);
      } catch {
        // Ignore invalid JSON
      }
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_DELAY);
  }

  function handleMessage(message: ServerMessage) {
    switch (message.type) {
      case "status":
        setStatus(message.status);
        setStatusMessage(message.message);
        setStatusElapsed(message.elapsed);
        break;

      case "transcript":
        for (const handler of transcriptHandlers) {
          handler({ timestamp: message.timestamp, text: message.text });
        }
        break;

      case "models":
        setModels(message.models);
        setActiveModelOp(null);
        break;

      case "config":
        setConfig(message.config);
        if ("auto_copy" in (message.config as any)) {
          setAutoCopy((message.config as any).auto_copy ?? false);
        }
        break;

      case "config_file":
        setConfigFileContent(message.content);
        setConfigFilePath(message.path);
        break;

      case "hotkey_press":
        for (const handler of hotkeyPressHandlers) {
          handler();
        }
        break;

      case "hotkey_release":
        for (const handler of hotkeyReleaseHandlers) {
          handler();
        }
        break;

      case "error":
        setStatus("error");
        setStatusMessage(message.message);
        setActiveModelOp(null);
        for (const handler of toastHandlers) {
          handler(message.message, "error");
        }
        break;

      case "toast":
        for (const handler of toastHandlers) {
          handler(message.message, message.level ?? "info");
        }
        break;

      case "download_progress":
        setDownloadProgress({ model: message.model, percent: message.percent });
        // Clear progress when download completes
        if (message.percent >= 100) {
          setTimeout(() => setDownloadProgress(null), 1000);
        }
        break;

      case "log":
        setLogs((prev) => {
          const entry: LogEntry = {
            id: logIdCounter++,
            level: message.level,
            message: message.message,
            timestamp: message.timestamp,
            source: message.source,
          };
          const next = [...prev, entry];
          // Keep last 200 log entries
          return next.length > 200 ? next.slice(-200) : next;
        });
        break;
    }
  }

  function send(message: ClientMessage) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }

  function downloadModel(name: string) {
    setActiveModelOp({ type: "pulling", model: name });
    setDownloadProgress(null);
    send({ type: "download_model", name });
  }

  function removeModel(name: string) {
    setActiveModelOp({ type: "removing", model: name });
    send({ type: "remove_model", name });
  }

  function requestConfigFile() {
    send({ type: "get_config_file" });
  }

  function onTranscript(handler: (entry: TranscriptEntry) => void) {
    transcriptHandlers.push(handler);
  }

  function onHotkeyPress(handler: () => void) {
    hotkeyPressHandlers.push(handler);
  }

  function onHotkeyRelease(handler: () => void) {
    hotkeyReleaseHandlers.push(handler);
  }

  function onToast(handler: (message: string, level: "info" | "error") => void) {
    toastHandlers.push(handler);
  }

  onMount(() => {
    connect();
  });

  onCleanup(() => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    ws?.close();
  });

  const value: BackendContextValue = {
    connected,
    status,
    statusMessage,
    statusElapsed,
    config,
    models,
    autoCopy,
    logs,
    configFileContent,
    configFilePath,
    downloadProgress,
    activeModelOp,
    downloadModel,
    removeModel,
    send,
    requestConfigFile,
    onTranscript,
    onHotkeyPress,
    onHotkeyRelease,
    onToast,
  };

  return <BackendProvider value={value}>{props.children}</BackendProvider>;
}
