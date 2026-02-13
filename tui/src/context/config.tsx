import { createEffect, createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { AppConfig } from "../types";

export interface ConfigContextValue {
  config: Accessor<AppConfig | null>;
  noiseEnabled: Accessor<boolean>;
  vadEnabled: Accessor<boolean>;
  autoCopy: Accessor<boolean>;
  hotkeyMode: Accessor<"ptt" | "toggle">;
  toggleNoise: () => void;
  toggleVad: () => void;
  toggleAutoCopy: () => void;
  toggleHotkeyMode: () => void;
}

const [ConfigProvider, useConfig] = createContextHelper<ConfigContextValue>("Config");
export { useConfig };

export function ConfigContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();

  const [noiseEnabled, setNoiseEnabled] = createSignal(true);
  const [vadEnabled, setVadEnabled] = createSignal(false);
  const [autoCopy, setAutoCopy] = createSignal(false);
  const [hotkeyMode, setHotkeyMode] = createSignal<"ptt" | "toggle">("ptt");

  // Sync with backend config
  createEffect(() => {
    const cfg = backend.config();
    if (cfg) {
      setNoiseEnabled(cfg.audio.noise_suppression.enabled);
      setVadEnabled(cfg.vad.enabled);
      setHotkeyMode(cfg.hotkey.mode);
    }
  });

  createEffect(() => {
    setAutoCopy(backend.autoCopy());
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
    const newValue = !autoCopy();
    setAutoCopy(newValue);
    backend.send({ type: "toggle_auto_copy", enabled: newValue });
  }

  function toggleHotkeyMode() {
    const nextMode = hotkeyMode() === "ptt" ? "toggle" : "ptt";
    setHotkeyMode(nextMode);
    backend.send({ type: "set_hotkey_mode", mode: nextMode });
  }

  const value: ConfigContextValue = {
    config: backend.config,
    noiseEnabled,
    vadEnabled,
    autoCopy,
    hotkeyMode,
    toggleNoise,
    toggleVad,
    toggleAutoCopy,
    toggleHotkeyMode,
  };

  return <ConfigProvider value={value}>{props.children}</ConfigProvider>;
}
