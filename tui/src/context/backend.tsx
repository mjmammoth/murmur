import {
  createSignal,
  onCleanup,
  onMount,
  type JSX,
  type Accessor,
} from "solid-js";
import { createContextHelper } from "./helper";
import type {
  AppConfig,
  ClientMessage,
  ServerMessage,
  ModelInfo,
  TranscriptEntry,
  AppStatus,
  LogEntry,
} from "../types";

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
  suppressPasteInputUntil: Accessor<number>;
  config: Accessor<AppConfig | null>;
  models: Accessor<ModelInfo[]>;
  autoCopy: Accessor<boolean>;
  autoPaste: Accessor<boolean>;
  logs: Accessor<LogEntry[]>;
  configFileContent: Accessor<string>;
  configFilePath: Accessor<string>;
  downloadProgress: Accessor<DownloadProgress | null>;
  activeModelOp: Accessor<ActiveModelOp | null>;
  downloadModel: (name: string) => void;
  cancelModelDownload: (name: string) => void;
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
  const [suppressPasteInputUntil, setSuppressPasteInputUntil] = createSignal(0);
  const [config, setConfig] = createSignal<AppConfig | null>(null);
  const [models, setModels] = createSignal<ModelInfo[]>([]);
  const [autoCopy, setAutoCopy] = createSignal(false);
  const [autoPaste, setAutoPaste] = createSignal(false);
  const [logs, setLogs] = createSignal<LogEntry[]>([]);
  const [configFileContent, setConfigFileContent] = createSignal("");
  const [configFilePath, setConfigFilePath] = createSignal("");
  const [downloadProgress, setDownloadProgress] = createSignal<DownloadProgress | null>(null);
  const [activeModelOp, setActiveModelOp] = createSignal<ActiveModelOp | null>(null);
  let logIdCounter = 0;

  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let unmounted = false;

  function clearReconnectTimer() {
    if (!reconnectTimer) return;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  // Event handlers
  const transcriptHandlers: ((entry: TranscriptEntry) => void)[] = [];
  const hotkeyPressHandlers: (() => void)[] = [];
  const hotkeyReleaseHandlers: (() => void)[] = [];
  const toastHandlers: ((message: string, level: "info" | "error") => void)[] = [];

  function connect() {
    if (unmounted) return;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    const socket = new WebSocket(`ws://${host}:${port}`);
    ws = socket;

    socket.onopen = () => {
      if (unmounted || ws !== socket) {
        socket.close();
        return;
      }
      clearReconnectTimer();
      setConnected(true);
      setStatus("connecting");
      setStatusMessage("Connected");
    };

    socket.onclose = () => {
      if (ws !== socket) return;
      ws = null;
      if (unmounted) return;
      setConnected(false);
      setStatus("connecting");
      setStatusMessage("Disconnected. Reconnecting...");
      scheduleReconnect();
    };

    socket.onerror = () => {
      if (ws !== socket || unmounted) return;
      setConnected(false);
      setStatus("error");
      setStatusMessage("Connection error");
    };

    socket.onmessage = (event) => {
      if (ws !== socket || unmounted) return;
      try {
        const message = JSON.parse(event.data) as ServerMessage;
        handleMessage(message);
      } catch {
        // Ignore invalid JSON
      }
    };
  }

  function scheduleReconnect() {
    if (unmounted || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (unmounted) return;
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

        const modelOp = activeModelOp();
        if (modelOp?.type === "pulling") {
          const pulled = message.models.find((model) => model.name === modelOp.model);
          if (pulled?.installed) {
            setActiveModelOp(null);
            setDownloadProgress(null);
          }
        } else if (modelOp?.type === "removing") {
          const removed = message.models.find((model) => model.name === modelOp.model);
          if (!removed || !removed.installed) {
            setActiveModelOp(null);
            setDownloadProgress(null);
          }
        }
        break;

      case "config":
        setConfig(message.config);
        if ("auto_copy" in message.config) {
          setAutoCopy(message.config.auto_copy ?? false);
        }
        if ("auto_paste" in message.config) {
          setAutoPaste(message.config.auto_paste ?? false);
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
        setDownloadProgress(null);
        for (const handler of toastHandlers) {
          handler(message.message, "error");
        }
        break;

      case "toast":
        if (activeModelOp()?.type === "pulling") {
          if (
            message.message.startsWith("Download cancelled:") ||
            message.message.startsWith("Download failed:") ||
            message.message.startsWith("Downloaded ")
          ) {
            setActiveModelOp(null);
            setDownloadProgress(null);
          }
        }
        if (
          activeModelOp()?.type === "removing" &&
          (message.message.startsWith("Removed ") || message.message.startsWith("Remove failed:"))
        ) {
          setActiveModelOp(null);
          setDownloadProgress(null);
        }
        for (const handler of toastHandlers) {
          handler(message.message, message.level ?? "info");
        }
        break;

      case "download_progress":
        setDownloadProgress({ model: message.model, percent: message.percent });
        setActiveModelOp((prev) => {
          if (prev?.type === "removing") return prev;
          if (prev?.type === "pulling" && prev.model === message.model) return prev;
          return { type: "pulling", model: message.model };
        });
        break;

      case "suppress_paste_input": {
        const durationMs = Number(message.duration_ms ?? 0);
        if (!Number.isFinite(durationMs) || durationMs <= 0) break;
        const suppressUntil = Date.now() + durationMs;
        setSuppressPasteInputUntil((prev) => Math.max(prev, suppressUntil));
        break;
      }

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

  function patchModelConfig(updater: (model: AppConfig["model"]) => AppConfig["model"]) {
    setConfig((prev) => {
      if (!prev) return prev;
      return { ...prev, model: updater(prev.model) };
    });
  }

  function patchHotkeyConfig(updater: (hotkey: AppConfig["hotkey"]) => AppConfig["hotkey"]) {
    setConfig((prev) => {
      if (!prev) return prev;
      return { ...prev, hotkey: updater(prev.hotkey) };
    });
  }

  function patchAudioConfig(updater: (audio: AppConfig["audio"]) => AppConfig["audio"]) {
    setConfig((prev) => {
      if (!prev) return prev;
      return { ...prev, audio: updater(prev.audio) };
    });
  }

  function patchVadConfig(updater: (vad: AppConfig["vad"]) => AppConfig["vad"]) {
    setConfig((prev) => {
      if (!prev) return prev;
      return { ...prev, vad: updater(prev.vad) };
    });
  }

  function patchOutputConfig(updater: (output: AppConfig["output"]) => AppConfig["output"]) {
    setConfig((prev) => {
      if (!prev) return prev;
      return { ...prev, output: updater(prev.output) };
    });
  }

  function patchUiConfig(
    updater: (ui: NonNullable<AppConfig["ui"]>) => NonNullable<AppConfig["ui"]>
  ) {
    setConfig((prev) => {
      if (!prev) return prev;
      const currentUi = prev.ui ?? { theme: "dark" };
      return { ...prev, ui: updater(currentUi) };
    });
  }

  function applyOptimisticConfig(message: ClientMessage) {
    switch (message.type) {
      case "set_selected_model":
      case "set_default_model":
        patchModelConfig((model) => ({ ...model, name: message.name, path: null }));
        return;
      case "set_model_backend":
        patchModelConfig((model) => ({ ...model, backend: message.backend }));
        return;
      case "set_model_device":
        patchModelConfig((model) => ({ ...model, device: message.device }));
        return;
      case "set_model_compute_type":
        patchModelConfig((model) => ({ ...model, compute_type: message.compute_type }));
        return;
      case "set_model_language":
        patchModelConfig((model) => ({ ...model, language: message.language }));
        return;
      case "set_hotkey_mode":
        patchHotkeyConfig((hotkey) => ({ ...hotkey, mode: message.mode }));
        return;
      case "set_hotkey":
        patchHotkeyConfig((hotkey) => ({ ...hotkey, key: message.hotkey }));
        return;
      case "set_audio_sample_rate":
        patchAudioConfig((audio) => ({ ...audio, sample_rate: message.sample_rate }));
        return;
      case "set_vad_aggressiveness":
        patchVadConfig((vad) => ({ ...vad, aggressiveness: message.aggressiveness }));
        return;
      case "set_output_clipboard":
        patchOutputConfig((output) => ({ ...output, clipboard: message.enabled }));
        return;
      case "set_output_file_enabled":
        patchOutputConfig((output) => ({
          ...output,
          file: { ...output.file, enabled: message.enabled },
        }));
        return;
      case "set_output_file_path":
        patchOutputConfig((output) => ({
          ...output,
          file: { ...output.file, path: message.path },
        }));
        return;
      case "set_model_path":
        patchModelConfig((model) => ({ ...model, path: message.path }));
        return;
      case "set_theme":
        patchUiConfig((ui) => ({ ...ui, theme: message.theme }));
        return;
      default:
        return;
    }
  }

  function send(message: ClientMessage) {
    if (ws?.readyState === WebSocket.OPEN) {
      applyOptimisticConfig(message);
      ws.send(JSON.stringify(message));
    }
  }

  function downloadModel(name: string) {
    setActiveModelOp({ type: "pulling", model: name });
    setDownloadProgress({ model: name, percent: 0 });
    send({ type: "download_model", name });
  }

  function removeModel(name: string) {
    setActiveModelOp({ type: "removing", model: name });
    setDownloadProgress(null);
    send({ type: "remove_model", name });
  }

  function cancelModelDownload(name: string) {
    send({ type: "cancel_model_download", name });
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
    unmounted = false;
    connect();
  });

  onCleanup(() => {
    unmounted = true;
    clearReconnectTimer();
    ws?.close();
    ws = null;
  });

  const value: BackendContextValue = {
    connected,
    status,
    statusMessage,
    statusElapsed,
    suppressPasteInputUntil,
    config,
    models,
    autoCopy,
    autoPaste,
    logs,
    configFileContent,
    configFilePath,
    downloadProgress,
    activeModelOp,
    downloadModel,
    cancelModelDownload,
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
