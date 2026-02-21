import { createEffect, createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { AppConfig } from "../types";

export interface ConfigContextValue {
  config: Accessor<AppConfig | null>;
  noiseEnabled: Accessor<boolean>;
  vadEnabled: Accessor<boolean>;
  autoCopy: Accessor<boolean>;
  autoPaste: Accessor<boolean>;
  autoRevertClipboard: Accessor<boolean>;
  outputClipboard: Accessor<boolean>;
  outputFileEnabled: Accessor<boolean>;
  hotkeyMode: Accessor<"ptt" | "toggle">;
  toggleNoise: () => void;
  toggleVad: () => void;
  toggleAutoCopy: () => void;
  toggleAutoPaste: () => void;
  toggleAutoRevertClipboard: () => void;
  toggleOutputClipboard: () => void;
  toggleOutputFileEnabled: () => void;
  toggleHotkeyMode: () => void;
  setAudioSampleRate: (sampleRate: number) => void;
  setVadAggressiveness: (aggressiveness: number) => void;
  setOutputFilePath: (path: string) => void;
  setModelPath: (path: string | null) => void;
}

const [ConfigProvider, useConfig] = createContextHelper<ConfigContextValue>("Config");
export { useConfig };

/**
 * Provides a ConfigContext to its children, exposing reactive configuration accessors and handlers that stay synchronized with backend state.
 *
 * The provider maintains local reactive signals for UI-driven flags (noise, VAD, output clipboard/file, hotkey mode), synchronizes them from backend.config(), and exposes action functions that send corresponding commands to the backend when invoked.
 *
 * @returns A JSX element that renders the ConfigProvider wrapping the given children with the computed configuration context value.
 */
export function ConfigContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();

  const [noiseEnabled, setNoiseEnabled] = createSignal(true);
  const [vadEnabled, setVadEnabled] = createSignal(false);
  const [outputClipboard, setOutputClipboard] = createSignal(true);
  const [outputFileEnabled, setOutputFileEnabled] = createSignal(false);
  const [hotkeyMode, setHotkeyMode] = createSignal<"ptt" | "toggle">("ptt");

  // Sync with backend config
  createEffect(() => {
    const cfg = backend.config();
    if (cfg) {
      setNoiseEnabled(cfg.audio.noise_suppression.enabled);
      setVadEnabled(cfg.vad.enabled);
      setHotkeyMode(cfg.hotkey.mode);
      setOutputClipboard(Boolean(cfg.output.clipboard));
      setOutputFileEnabled(Boolean(cfg.output.file.enabled));
    }
  });

  function toggleNoise() {
    const newValue = !noiseEnabled();
    setNoiseEnabled(newValue);
    backend.send({ type: "toggle_noise", enabled: newValue });
  }

  function toggleVad() {
    const newValue = !vadEnabled();
    setVadEnabled(newValue);
    backend.send({ type: "toggle_vad", enabled: newValue });
  }

  function toggleAutoCopy() {
    const newValue = !backend.autoCopy();
    backend.send({ type: "toggle_auto_copy", enabled: newValue });
  }

  function toggleAutoPaste() {
    const newValue = !backend.autoPaste();
    backend.send({ type: "toggle_auto_paste", enabled: newValue });
  }

  function toggleAutoRevertClipboard() {
    const newValue = !backend.autoRevertClipboard();
    backend.send({ type: "toggle_auto_revert_clipboard", enabled: newValue });
  }

  function toggleHotkeyMode() {
    const nextMode = hotkeyMode() === "ptt" ? "toggle" : "ptt";
    setHotkeyMode(nextMode);
    backend.send({ type: "set_hotkey_mode", mode: nextMode });
  }

  function toggleOutputClipboard() {
    const nextEnabled = !outputClipboard();
    setOutputClipboard(nextEnabled);
    backend.send({ type: "set_output_clipboard", enabled: nextEnabled });
  }

  function toggleOutputFileEnabled() {
    const nextEnabled = !outputFileEnabled();
    setOutputFileEnabled(nextEnabled);
    backend.send({ type: "set_output_file_enabled", enabled: nextEnabled });
  }

  function setAudioSampleRate(sampleRate: number) {
    backend.send({ type: "set_audio_sample_rate", sample_rate: sampleRate });
  }

  function setVadAggressiveness(aggressiveness: number) {
    backend.send({ type: "set_vad_aggressiveness", aggressiveness });
  }

  function setOutputFilePath(path: string) {
    backend.send({ type: "set_output_file_path", path });
  }

  function setModelPath(path: string | null) {
    backend.send({ type: "set_model_path", path });
  }

  const value: ConfigContextValue = {
    config: backend.config,
    noiseEnabled,
    vadEnabled,
    autoCopy: backend.autoCopy,
    autoPaste: backend.autoPaste,
    autoRevertClipboard: backend.autoRevertClipboard,
    outputClipboard,
    outputFileEnabled,
    hotkeyMode,
    toggleNoise,
    toggleVad,
    toggleAutoCopy,
    toggleAutoPaste,
    toggleAutoRevertClipboard,
    toggleOutputClipboard,
    toggleOutputFileEnabled,
    toggleHotkeyMode,
    setAudioSampleRate,
    setVadAggressiveness,
    setOutputFilePath,
    setModelPath,
  };

  return <ConfigProvider value={value}>{props.children}</ConfigProvider>;
}
