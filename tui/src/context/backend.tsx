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
  RuntimeName,
  ClientMessage,
  ServerMessage,
  ModelInfo,
  TranscriptEntry,
  AppStatus,
  LogEntry,
  RuntimeCapabilities,
} from "../types";
import { appendLogWithLimit, formatClientLogTimestamp } from "./backend-log";

export interface DownloadProgress {
  model: string;
  runtime: RuntimeName;
  percent: number;
}

export interface ActiveModelOp {
  type: "pulling" | "removing";
  model: string;
  runtime: RuntimeName;
}

export interface CapabilitiesResponse {
  capabilities: RuntimeCapabilities;
  recommended: { runtime: string; device: string };
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
  autoRevertClipboard: Accessor<boolean>;
  logs: Accessor<LogEntry[]>;
  appendClientLog: (entry: { level: string; message: string; source?: string }) => void;
  configFileContent: Accessor<string>;
  configFilePath: Accessor<string>;
  downloadProgress: Accessor<DownloadProgress | null>;
  activeModelOp: Accessor<ActiveModelOp | null>;
  capabilitiesResponse: Accessor<CapabilitiesResponse | null>;
  isModelPullQueued: (name: string, runtime?: RuntimeName) => boolean;
  downloadModel: (
    name: string,
    runtime?: RuntimeName,
    activateRuntime?: RuntimeName | null,
  ) => void;
  cancelModelDownload: (name: string, runtime?: RuntimeName) => void;
  cancelAllModelDownloads: () => void;
  hasPendingModelDownloads: () => boolean;
  removeModel: (name: string, runtime?: RuntimeName) => void;
  send: (message: ClientMessage) => boolean;
  requestConfigFile: () => void;
  requestCapabilities: () => void;
  onTranscript: (handler: (entry: TranscriptEntry) => void) => void;
  onHotkeyPress: (handler: () => void) => void;
  onHotkeyRelease: (handler: () => void) => void;
  onToast: (handler: (message: string, level: "info" | "error") => void) => void;
  onRuntimeSwitchRequired: (
    handler: (payload: { runtime: RuntimeName; model: string; format: string }) => void,
  ) => () => void;
}

const [BackendProvider, useBackend] = createContextHelper<BackendContextValue>("Backend");
export { useBackend };

const RECONNECT_DELAY = 2000;

/**
 * Provide a runtime WebSocket context and manage connection, server-derived state, and related actions for child components.
 *
 * @param props.host - Optional runtime host (default: "localhost")
 * @param props.port - Optional runtime port (default: 7878)
 * @param props.children - The component subtree that consumes the runtime context
 * @returns A JSX element that supplies the BackendContext to `props.children`
 */
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
  const [autoRevertClipboard, setAutoRevertClipboard] = createSignal(false);
  const [logs, setLogs] = createSignal<LogEntry[]>([]);
  const [configFileContent, setConfigFileContent] = createSignal("");
  const [configFilePath, setConfigFilePath] = createSignal("");
  const [downloadProgress, setDownloadProgress] = createSignal<DownloadProgress | null>(null);
  const [activeModelOp, setActiveModelOp] = createSignal<ActiveModelOp | null>(null);
  const [capabilitiesResponse, setCapabilitiesResponse] = createSignal<CapabilitiesResponse | null>(null);
  const [queuedModelPullKeys, setQueuedModelPullKeys] = createSignal<string[]>([]);
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
  const runtimeSwitchRequiredHandlers: (
    (payload: { runtime: RuntimeName; model: string; format: string }) => void
  )[] = [];

  function modelPullKey(name: string, runtime: RuntimeName) {
    return `${runtime}:${name}`;
  }

  function queueModelPull(name: string, runtime: RuntimeName) {
    const key = modelPullKey(name, runtime);
    setQueuedModelPullKeys((prev) => (prev.includes(key) ? prev : [...prev, key]));
  }

  function dequeueModelPull(name: string, runtime: RuntimeName) {
    const key = modelPullKey(name, runtime);
    setQueuedModelPullKeys((prev) => prev.filter((candidate) => candidate !== key));
  }

  function dequeueModelPullByName(name: string) {
    setQueuedModelPullKeys((prev) => prev.filter((candidate) => !candidate.endsWith(`:${name}`)));
  }

  function isModelPullQueued(
    name: string,
    runtime: RuntimeName = (config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper",
  ) {
    return queuedModelPullKeys().includes(modelPullKey(name, runtime));
  }

  function emitToast(message: string, level: "info" | "error") {
    for (const handler of toastHandlers) {
      handler(message, level);
    }
  }

  function emitRuntimeSwitchRequired(payload: {
    runtime: RuntimeName;
    model: string;
    format: string;
  }) {
    for (const handler of runtimeSwitchRequiredHandlers) {
      handler(payload);
    }
  }

  function appendClientLog(entry: { level: string; message: string; source?: string }) {
    setLogs((prev) => {
      const nextEntry: LogEntry = {
        id: logIdCounter++,
        level: entry.level,
        message: entry.message,
        timestamp: formatClientLogTimestamp(),
        source: entry.source ?? "tui.ui",
      };
      return appendLogWithLimit(prev, nextEntry);
    });
  }

  function sendInternal(message: ClientMessage): boolean {
    if (ws?.readyState === WebSocket.OPEN) {
      applyOptimisticConfig(message);
      ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

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
      setQueuedModelPullKeys([]);
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

  /**
   * Process an incoming ServerMessage, update runtime signals, and notify registered handlers.
   *
   * This updates connection and application state (status, config, models, download progress, active model operations, suppress-paste timers, and logs) and invokes transcript, hotkey, and toast handlers as appropriate based on the message type.
   *
   * @param message - The server message to handle
   */
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

      case "models": {
        setModels(message.models);
        const installedPullKeys = new Set<string>();
        for (const model of message.models) {
          for (const variantRuntime of Object.keys(model.variants) as RuntimeName[]) {
            if (model.variants[variantRuntime]?.installed) {
              installedPullKeys.add(modelPullKey(model.name, variantRuntime));
            }
          }
        }
        setQueuedModelPullKeys((prev) => prev.filter((key) => !installedPullKeys.has(key)));

        const modelOp = activeModelOp();
        if (modelOp?.type === "pulling") {
          const pulled = message.models.find((model) => model.name === modelOp.model);
          if (pulled?.variants?.[modelOp.runtime]?.installed) {
            setActiveModelOp(null);
            setDownloadProgress(null);
          }
        } else if (modelOp?.type === "removing") {
          const removed = message.models.find((model) => model.name === modelOp.model);
          if (!removed || !removed.variants?.[modelOp.runtime]?.installed) {
            setActiveModelOp(null);
            setDownloadProgress(null);
          }
        }
        break;
      }

      case "config":
        setConfig(message.config);
        if ("auto_copy" in message.config) {
          setAutoCopy(message.config.auto_copy ?? false);
        }
        if ("auto_paste" in message.config) {
          setAutoPaste(message.config.auto_paste ?? false);
        }
        if ("auto_revert_clipboard" in message.config) {
          setAutoRevertClipboard(message.config.auto_revert_clipboard ?? false);
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
        setQueuedModelPullKeys([]);
        emitToast(message.message, "error");
        break;

      case "toast": {
        const modelOp = activeModelOp();
        const pullAction = message.action === "download_cancelled" ||
          message.action === "download_failed" ||
          message.action === "download_complete";
        if (pullAction && message.model) {
          if (message.runtime) {
            dequeueModelPull(message.model, message.runtime);
          } else {
            dequeueModelPullByName(message.model);
          }
        }
        if (
          modelOp?.type === "pulling" &&
          pullAction &&
          (!message.model || message.model === modelOp.model) &&
          (!message.runtime || message.runtime === modelOp.runtime)
        ) {
          setActiveModelOp(null);
          setDownloadProgress(null);
        }
        if (
          modelOp?.type === "removing" &&
          (message.action === "remove_complete" || message.action === "remove_failed")
        ) {
          setActiveModelOp(null);
          setDownloadProgress(null);
        }
        emitToast(message.message, message.level ?? "info");
        break;
      }

      case "download_progress":
        dequeueModelPull(message.model, message.runtime);
        setDownloadProgress({
          model: message.model,
          runtime: message.runtime,
          percent: message.percent,
        });
        setActiveModelOp((prev) => {
          if (prev?.type === "removing") return prev;
          if (
            prev?.type === "pulling" &&
            prev.model === message.model &&
            prev.runtime === message.runtime
          ) {
            return prev;
          }
          return { type: "pulling", model: message.model, runtime: message.runtime };
        });
        break;

      case "runtime_switch_requires_model_variant":
        emitRuntimeSwitchRequired({
          runtime: message.runtime,
          model: message.model,
          format: message.format,
        });
        break;

      case "suppress_paste_input": {
        const durationMs = Number(message.duration_ms ?? 0);
        if (!Number.isFinite(durationMs) || durationMs <= 0) break;
        const suppressUntil = Date.now() + durationMs;
        setSuppressPasteInputUntil((prev) => Math.max(prev, suppressUntil));
        break;
      }

      case "capabilities":
        setCapabilitiesResponse({
          capabilities: message.capabilities,
          recommended: message.recommended,
        });
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
          return appendLogWithLimit(prev, entry);
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
      case "set_model_runtime":
        // Runtime switch can now require explicit model-variant confirmation.
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
      case "toggle_auto_revert_clipboard":
        setAutoRevertClipboard(message.enabled);
        setConfig((prev) => {
          if (!prev) return prev;
          return { ...prev, auto_revert_clipboard: message.enabled };
        });
        return;
      default:
        return;
    }
  }

  function send(message: ClientMessage): boolean {
    return sendInternal(message);
  }

  function downloadModel(
    name: string,
    runtime?: RuntimeName,
    activateRuntime: RuntimeName | null = null,
  ) {
    const selectedRuntime = runtime ?? (config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper";
    if (isModelPullQueued(name, selectedRuntime)) return;
    const op = activeModelOp();
    if (op) {
      if (op.type === "pulling" && op.model === name && op.runtime === selectedRuntime) return;
      const sent = sendInternal({
        type: "download_model",
        name,
        runtime: selectedRuntime,
        activate_runtime: activateRuntime,
      });
      if (!sent) {
        emitToast("Unable to queue model download while disconnected from runtime.", "error");
        return;
      }
      queueModelPull(name, selectedRuntime);
      const pendingOp = op.type === "pulling"
        ? `pulling ${op.model} (${op.runtime})`
        : `removing ${op.model} (${op.runtime})`;
      emitToast(`Queued ${name}. It will start after ${pendingOp}.`, "info");
      return;
    }
    const sent = sendInternal({
      type: "download_model",
      name,
      runtime: selectedRuntime,
      activate_runtime: activateRuntime,
    });
    if (!sent) {
      emitToast("Unable to start model download while disconnected from runtime.", "error");
      return;
    }
    dequeueModelPull(name, selectedRuntime);
    setActiveModelOp({ type: "pulling", model: name, runtime: selectedRuntime });
    setDownloadProgress({ model: name, runtime: selectedRuntime, percent: 0 });
  }

  /**
   * Initiates removal of a model on the runtime.
   *
   * Marks the model as being removed, clears any active download progress for it, and sends a `remove_model` request to the server.
   *
   * @param name - The name of the model to remove
   */
  function removeModel(name: string, runtime?: RuntimeName) {
    const selectedRuntime = runtime ?? (config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper";
    const sent = sendInternal({ type: "remove_model", name, runtime: selectedRuntime });
    if (!sent) {
      emitToast("Unable to remove model while disconnected from runtime.", "error");
      return;
    }
    setActiveModelOp({ type: "removing", model: name, runtime: selectedRuntime });
    setDownloadProgress(null);
  }

  /**
   * Requests cancellation of an in-progress model download.
   *
   * @param name - The name of the model whose download should be canceled
   */
  function cancelModelDownload(name: string, runtime?: RuntimeName) {
    const selectedRuntime = runtime ?? (config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper";
    const sent = send({ type: "cancel_model_download", name, runtime: selectedRuntime });
    if (!sent) {
      emitToast("Unable to cancel model download while disconnected from runtime.", "error");
      return;
    }
    dequeueModelPull(name, selectedRuntime);
  }

  function cancelAllModelDownloads() {
    const sent = send({ type: "cancel_all_model_downloads" });
    if (!sent) {
      emitToast("Unable to cancel model downloads while disconnected from runtime.", "error");
      return;
    }
    setQueuedModelPullKeys([]);
  }

  function hasPendingModelDownloads() {
    const op = activeModelOp();
    if (op?.type === "pulling") return true;
    return queuedModelPullKeys().length > 0;
  }

  /**
   * Request the runtime to send the current configuration file.
   *
   * Sends a `get_config_file` request to the server so the client will receive the configuration file content and path.
   */
  function requestConfigFile() {
    send({ type: "get_config_file" });
  }

  function requestCapabilities() {
    send({ type: "get_capabilities" });
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

  function onRuntimeSwitchRequired(
    handler: (payload: { runtime: RuntimeName; model: string; format: string }) => void,
  ) {
    runtimeSwitchRequiredHandlers.push(handler);
    return () => {
      const index = runtimeSwitchRequiredHandlers.indexOf(handler);
      if (index >= 0) {
        runtimeSwitchRequiredHandlers.splice(index, 1);
      }
    };
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
    autoRevertClipboard,
    logs,
    appendClientLog,
    configFileContent,
    configFilePath,
    downloadProgress,
    activeModelOp,
    capabilitiesResponse,
    isModelPullQueued,
    downloadModel,
    cancelModelDownload,
    cancelAllModelDownloads,
    hasPendingModelDownloads,
    removeModel,
    send,
    requestConfigFile,
    requestCapabilities,
    onTranscript,
    onHotkeyPress,
    onHotkeyRelease,
    onToast,
    onRuntimeSwitchRequired,
  };

  return <BackendProvider value={value}>{props.children}</BackendProvider>;
}
