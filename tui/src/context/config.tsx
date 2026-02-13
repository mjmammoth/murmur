import { createEffect, createSignal, type JSX, type Accessor } from "solid-js";
import { createContextHelper } from "./helper";
import { useBackend } from "./backend";
import type { AppConfig } from "../types";

export interface ConfigContextValue {
  config: Accessor<AppConfig | null>;
  noiseEnabled: Accessor<boolean>;
  vadEnabled: Accessor<boolean>;
  autoCopy: Accessor<boolean>;
  toggleNoise: () => void;
  toggleVad: () => void;
  toggleAutoCopy: () => void;
}

const [ConfigProvider, useConfig] = createContextHelper<ConfigContextValue>("Config");
export { useConfig };

export function ConfigContextProvider(props: { children: JSX.Element }): JSX.Element {
  const backend = useBackend();

  const [noiseEnabled, setNoiseEnabled] = createSignal(true);
  const [vadEnabled, setVadEnabled] = createSignal(false);
  const [autoCopy, setAutoCopy] = createSignal(false);

  // Sync with backend config
  createEffect(() => {
    const cfg = backend.config();
    if (cfg) {
      setNoiseEnabled(cfg.audio.noise_suppression.enabled);
      setVadEnabled(cfg.vad.enabled);
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

  const value: ConfigContextValue = {
    config: backend.config,
    noiseEnabled,
    vadEnabled,
    autoCopy,
    toggleNoise,
    toggleVad,
    toggleAutoCopy,
  };

  return <ConfigProvider value={value}>{props.children}</ConfigProvider>;
}
