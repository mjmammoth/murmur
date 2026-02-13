// Configuration types (mirroring Python dataclasses)

export interface ModelConfig {
  name: string;
  device: string;
  compute_type: string;
  auto_download: boolean;
  path: string | null;
  language: string | null;
}

export interface HotkeyConfig {
  mode: "ptt" | "toggle";
  key: string;
}

export interface NoiseSuppressionConfig {
  enabled: boolean;
  level: number;
}

export interface AudioConfig {
  sample_rate: number;
  noise_suppression: NoiseSuppressionConfig;
}

export interface VadConfig {
  enabled: boolean;
  aggressiveness: number;
  min_speech_ms: number;
  max_silence_ms: number;
}

export interface FileOutputConfig {
  enabled: boolean;
  path: string;
}

export interface OutputConfig {
  clipboard: boolean;
  file: FileOutputConfig;
}

export interface BridgeConfig {
  host: string;
  port: number;
}

export interface AppConfig {
  model: ModelConfig;
  hotkey: HotkeyConfig;
  audio: AudioConfig;
  vad: VadConfig;
  output: OutputConfig;
  bridge: BridgeConfig;
  auto_copy?: boolean;
}

// Transcript types

export interface TranscriptEntry {
  timestamp: string;
  text: string;
}

// Model manager types

export interface ModelInfo {
  name: string;
  installed: boolean;
  path: string | null;
}

// Application status

export type AppStatus =
  | "connecting"
  | "ready"
  | "recording"
  | "transcribing"
  | "downloading"
  | "error";

// WebSocket message types

// Client -> Server messages
export type ClientMessage =
  | { type: "start_recording" }
  | { type: "stop_recording" }
  | { type: "toggle_noise"; enabled: boolean }
  | { type: "toggle_vad"; enabled: boolean }
  | { type: "toggle_auto_copy"; enabled: boolean }
  | { type: "set_hotkey_blocked"; enabled: boolean }
  | { type: "download_model"; name: string }
  | { type: "remove_model"; name: string }
  | { type: "set_default_model"; name: string }
  | { type: "set_hotkey"; hotkey: string }
  | { type: "list_models" }
  | { type: "get_config" }
  | { type: "get_config_file" }
  | { type: "copy_text"; text: string };

// Server -> Client messages
export type ServerMessage =
  | { type: "status"; status: AppStatus; message: string; elapsed?: number }
  | { type: "transcript"; timestamp: string; text: string }
  | { type: "models"; models: ModelInfo[] }
  | { type: "config"; config: AppConfig }
  | { type: "hotkey_press" }
  | { type: "hotkey_release" }
  | { type: "error"; message: string }
  | { type: "config_file"; content: string; path: string }
  | { type: "toast"; message: string; level?: "info" | "error" }
  | { type: "log"; level: string; message: string; timestamp: string; source: string }
  | { type: "download_progress"; model: string; percent: number };

// Log types

export interface LogEntry {
  id: number;
  level: string;
  message: string;
  timestamp: string;
  source: string;
}

// Toast types

export interface Toast {
  id: number;
  message: string;
  level: "info" | "error";
}

// Dialog types

export type DialogType = "model-manager" | "settings" | "hotkey";

export interface DialogState {
  type: DialogType;
  data?: unknown;
}
