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
  onTranscriptHistory: (handler: (entries: TranscriptEntry[]) => void) => () => void;
  onTranscript: (handler: (entry: TranscriptEntry) => void) => () => void;
  onHotkeyPress: (handler: () => void) => () => void;
  onHotkeyRelease: (handler: () => void) => () => void;
  onToast: (handler: (message: string, level: "info" | "error") => void) => () => void;
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
  const transcriptHistoryHandlers: ((entries: TranscriptEntry[]) => void)[] = [];
  const hotkeyPressHandlers: (() => void)[] = [];
  const hotkeyReleaseHandlers: (() => void)[] = [];
  const toastHandlers: ((message: string, level: "info" | "error") => void)[] = [];
  const runtimeSwitchRequiredHandlers: (
    (payload: { runtime: RuntimeName; model: string; format: string }) => void
  )[] = [];

  function registerHandler<T>(handlers: T[], handler: T): () => void {
    handlers.push(handler);
    return () => {
      const index = handlers.indexOf(handler);
      if (index >= 0) {
        handlers.splice(index, 1);
      }
    };
  }

  /**
   * Create a unique queue key for a model within a specific runtime.
   *
   * @param name - The model's name
   * @param runtime - The runtime identifier
   * @returns The composed key in the format `runtime:name`
   */
  function modelPullKey(name: string, runtime: RuntimeName) {
    return `${runtime}:${name}`;
  }

  /**
   * Adds a model pull (for a specific runtime) to the pending download queue if it is not already queued.
   *
   * @param name - The model name to queue for download
   * @param runtime - The runtime variant for which the model should be pulled
   */
  function queueModelPull(name: string, runtime: RuntimeName) {
    const key = modelPullKey(name, runtime);
    setQueuedModelPullKeys((prev) => (prev.includes(key) ? prev : [...prev, key]));
  }

  /**
   * Remove a queued model-pull entry for the given model and runtime.
   *
   * @param name - Model name whose pull request should be removed from the queue
   * @param runtime - Runtime variant associated with the queued pull
   */
  function dequeueModelPull(name: string, runtime: RuntimeName) {
    const key = modelPullKey(name, runtime);
    setQueuedModelPullKeys((prev) => prev.filter((candidate) => candidate !== key));
  }

  /**
   * Remove all queued model-pull entries for the given model name across all runtimes.
   *
   * @param name - The model name whose pending pull entries should be removed from the queue
   */
  function dequeueModelPullByName(name: string) {
    setQueuedModelPullKeys((prev) => prev.filter((candidate) => !candidate.endsWith(`:${name}`)));
  }

  /**
   * Checks whether a pull for a specific model is queued for a given runtime.
   *
   * @param name - The model name to check
   * @param runtime - The runtime to check for; defaults to the configured model runtime or `"faster-whisper"` if none is set
   * @returns `true` if a pull for `name` is queued for `runtime`, `false` otherwise
   */
  function isModelPullQueued(
    name: string,
    runtime: RuntimeName = (config()?.model.runtime as RuntimeName | undefined) ?? "faster-whisper",
  ) {
    return queuedModelPullKeys().includes(modelPullKey(name, runtime));
  }

  /**
   * Notify all registered toast handlers with a message and severity.
   *
   * @param message - The toast text to deliver to handlers
   * @param level - The toast severity, either `"info"` or `"error"`
   */
  function emitToast(message: string, level: "info" | "error") {
    for (const handler of toastHandlers) {
      handler(message, level);
    }
  }

  /**
   * Notify all registered handlers that the runtime must switch to a specific model variant.
   *
   * @param payload - Object describing the required runtime switch:
   *   - `runtime`: target runtime name
   *   - `model`: model identifier that requires the runtime variant
   *   - `format`: model format required by the runtime
   */
  function emitRuntimeSwitchRequired(payload: {
    runtime: RuntimeName;
    model: string;
    format: string;
  }) {
    for (const handler of runtimeSwitchRequiredHandlers) {
      handler(payload);
    }
  }

  /**
   * Appends a client-side log entry to the internal log list.
   *
   * The function assigns a unique numeric `id`, adds a formatted timestamp, and
   * uses `"tui.ui"` as the default `source` when none is provided. The entry is
   * appended while enforcing the configured log length limit.
   *
   * @param entry - Object with `level` (e.g., `"info"`, `"error"`), `message`, and optional `source`
   */
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

  /**
   * Send a client message over the active WebSocket and apply optimistic UI config updates when applicable.
   *
   * @param message - The ClientMessage to send to the backend
   * @returns `true` if the message was sent (WebSocket was open), `false` otherwise
   */
  function sendInternal(message: ClientMessage): boolean {
    if (ws?.readyState === WebSocket.OPEN) {
      applyOptimisticConfig(message);
      ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /**
   * Establishes and manages the WebSocket connection to the backend server.
   *
   * Creates a WebSocket to ws://host:port, installs handlers that update connection state and status messages,
   * dispatch valid incoming server messages to the internal message processor, clear and manage the model-pull
   * queue on disconnect, and schedule reconnect attempts. The function is no-op if the provider is unmounted or
   * if an active socket already exists.
   */
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

  /**
   * Schedule a single delayed reconnection attempt if one is not already pending and the provider is mounted.
   *
   * Sets a timer that will call `connect()` after `RECONNECT_DELAY` unless the provider has been unmounted
   * or the timer is cleared before it fires.
   */
  function scheduleReconnect() {
    if (unmounted || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (unmounted) return;
      connect();
    }, RECONNECT_DELAY);
  }

  /**
   * Handle a ServerMessage by updating backend state and invoking registered handlers.
   *
   * Updates connection status, configuration, model lists, download progress, active model operations,
   * suppress-paste timers, logs, and emits transcript, hotkey, toast, and runtime-switch events as appropriate.
   *
   * @param message - The server message to process
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
          handler({
            id: message.id,
            timestamp: message.timestamp,
            text: message.text,
            created_at: message.created_at,
          });
        }
        break;
      case "transcript_history":
        for (const handler of transcriptHistoryHandlers) {
          handler(message.entries);
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

  /**
   * Apply optimistic UI updates to local configuration and state based on a client message.
   *
   * Updates relevant config slices (model, hotkey, audio, VAD, output, UI) or local flags to
   * reflect the intended change immediately in the frontend without waiting for a backend confirmation.
   *
   * @param message - The client message describing the intended configuration change
   */
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
      case "set_audio_input_device":
        patchAudioConfig((audio) => ({ ...audio, input_device: message.device_key }));
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

  /**
   * Send a client message to the runtime server over the active WebSocket connection.
   *
   * @param message - The client message to transmit to the backend runtime
   * @returns `true` if the message was sent (connection open), `false` otherwise
   */
  function send(message: ClientMessage): boolean {
    return sendInternal(message);
  }

  /**
   * Initiates or queues a model download for a specific runtime.
   *
   * If a download or removal is already in progress this call will queue the requested pull; if the model is already queued or actively being pulled for the target runtime, the call is a no-op. When started it sends a `download_model` request to the runtime, sets the active model operation to pulling, and initializes download progress. Emits user-facing toasts for queueing and connection failures.
   *
   * @param name - Model name to download
   * @param runtime - Optional runtime to target; if omitted the provider's selected model runtime is used, falling back to `"faster-whisper"`
   * @param activateRuntime - Optional runtime to activate after download; pass `null` to avoid activating any runtime
   */
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
   * Remove a model from a specific runtime.
   *
   * Sends a `remove_model` request for the given model and runtime, marks the model as being removed, and clears any download progress for that model. If `runtime` is omitted, uses the current configured model runtime or `"faster-whisper"` as a fallback. If the client is disconnected, emits an error toast and does not send the request.
   *
   * @param name - The name of the model to remove
   * @param runtime - Optional runtime to target; defaults to the configured model runtime or `"faster-whisper"`
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
   * Cancel an ongoing or queued download for a specific model.
   *
   * @param name - Model name whose download should be canceled
   * @param runtime - Target runtime for the cancellation; if omitted uses the configured model runtime or falls back to `"faster-whisper"`
   *
   * Notes: If the provider is not connected, an error toast is emitted and no queue changes are made.
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

  /**
   * Cancel all pending model downloads and clear the local download queue.
   *
   * If the cancel request cannot be sent because the provider is disconnected, emits an error toast and leaves the queued downloads unchanged.
   */
  function cancelAllModelDownloads() {
    const sent = send({ type: "cancel_all_model_downloads" });
    if (!sent) {
      emitToast("Unable to cancel model downloads while disconnected from runtime.", "error");
      return;
    }
    setQueuedModelPullKeys([]);
  }

  /**
   * Indicates whether there are any pending model downloads.
   *
   * Checks if a model is currently being pulled or if there are queued model pulls.
   *
   * @returns `true` if a pulling operation is active or there are queued model pulls, `false` otherwise.
   */
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
    return registerHandler(transcriptHandlers, handler);
  }

  function onTranscriptHistory(handler: (entries: TranscriptEntry[]) => void) {
    return registerHandler(transcriptHistoryHandlers, handler);
  }

  function onHotkeyPress(handler: () => void) {
    return registerHandler(hotkeyPressHandlers, handler);
  }

  function onHotkeyRelease(handler: () => void) {
    return registerHandler(hotkeyReleaseHandlers, handler);
  }

  /**
   * Register a handler that will be invoked whenever a toast message is emitted.
   *
   * @param handler - Function called with the toast `message` and its `level` (`"info"` or `"error"`)
   */
  function onToast(handler: (message: string, level: "info" | "error") => void) {
    return registerHandler(toastHandlers, handler);
  }

  /**
   * Register a handler invoked when the runtime requires switching to a specific model variant.
   *
   * @param handler - Callback invoked with a payload containing `runtime` (the runtime to switch to), `model` (the model name), and `format` (the model format).
   * @returns A function that unregisters the provided handler.
   */
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
    onTranscriptHistory,
    onTranscript,
    onHotkeyPress,
    onHotkeyRelease,
    onToast,
    onRuntimeSwitchRequired,
  };

  return <BackendProvider value={value}>{props.children}</BackendProvider>;
}
