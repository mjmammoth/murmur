// Configuration types (mirroring Python dataclasses)

export interface RuntimeOptionState {
  enabled: boolean;
  reason: string | null;
}

export type RuntimeName = "faster-whisper" | "whisper.cpp";

export interface RuntimeModelCapabilities {
  runtimes: Record<string, RuntimeOptionState>;
  devices_by_runtime: Record<string, Record<string, RuntimeOptionState>>;
  compute_types_by_runtime_device: Record<string, Record<string, string[]>>;
  devices: Record<string, RuntimeOptionState>;
  compute_types_by_device: Record<string, string[]>;
}

export interface RuntimeCapabilities {
  model: RuntimeModelCapabilities;
}

export interface PlatformCapabilities {
  hotkey_capture: boolean;
  hotkey_swallow: boolean;
  status_indicator: boolean;
  auto_paste: boolean;
  hotkey_guidance: string | null;
}

export interface ModelConfig {
  name: string;
  runtime: string;
  device: string;
  compute_type: string;
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
  input_device: string | null;
  noise_suppression: NoiseSuppressionConfig;
}

export interface AudioInputDeviceOption {
  key: string;
  index: number;
  name: string;
  hostapi: string;
  max_input_channels: number;
  default_samplerate: number | null;
  is_default: boolean;
  sample_rate_supported: boolean | null;
  sample_rate_reason: string | null;
}

export interface AudioInputsConfig {
  devices: AudioInputDeviceOption[];
  default_key: string | null;
  selected_key: string | null;
  active_key: string | null;
  selected_missing: boolean;
  selected_missing_reason: string | null;
  scan_error: string | null;
  sample_rate: number;
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

export interface UiConfig {
  theme: string;
  welcome_shown?: boolean;
}

export interface AppConfig {
  model: ModelConfig;
  hotkey: HotkeyConfig;
  audio: AudioConfig;
  vad: VadConfig;
  output: OutputConfig;
  bridge: BridgeConfig;
  ui?: UiConfig;
  auto_copy?: boolean;
  auto_paste?: boolean;
  auto_revert_clipboard?: boolean;
  first_run_setup_required?: boolean;
  runtime?: RuntimeCapabilities;
  audio_inputs?: AudioInputsConfig;
  version?: string;
  platform_capabilities?: PlatformCapabilities;
}

// Transcript types

export interface TranscriptEntry {
  id?: number;
  timestamp: string;
  text: string;
  created_at?: string;
}

// Model manager types

export interface ModelInfo {
  name: string;
  variants: Record<RuntimeName, ModelVariantInfo>;
}

export interface ModelVariantInfo {
  runtime: RuntimeName;
  format: string;
  installed: boolean;
  path: string | null;
  size_bytes?: number | null;
  size_estimated?: boolean;
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
  | { type: "transcribe_paste"; text: string }
  | { type: "toggle_noise"; enabled: boolean }
  | { type: "toggle_vad"; enabled: boolean }
  | { type: "toggle_auto_copy"; enabled: boolean }
  | { type: "toggle_auto_paste"; enabled: boolean }
  | { type: "toggle_auto_revert_clipboard"; enabled: boolean }
  | { type: "set_hotkey_blocked"; enabled: boolean }
  | { type: "set_hotkey_mode"; mode: "ptt" | "toggle" }
  | { type: "set_hotkey"; hotkey: string }
  | { type: "set_audio_sample_rate"; sample_rate: number }
  | { type: "set_audio_input_device"; device_key: string | null }
  | { type: "refresh_audio_inputs" }
  | { type: "set_vad_aggressiveness"; aggressiveness: number }
  | { type: "set_output_clipboard"; enabled: boolean }
  | { type: "set_output_file_enabled"; enabled: boolean }
  | { type: "set_output_file_path"; path: string }
  | { type: "set_model_path"; path: string | null }
  | { type: "set_selected_model"; name: string }
  // Backward-compatible alias for set_selected_model
  | { type: "set_default_model"; name: string }
  | { type: "set_model_runtime"; runtime: string }
  | { type: "set_model_device"; device: string }
  | { type: "set_model_compute_type"; compute_type: string }
  | { type: "set_model_language"; language: string | null }
  | { type: "set_theme"; theme: string }
  | { type: "download_model"; name: string; runtime?: RuntimeName; activate_runtime?: RuntimeName | null }
  | { type: "cancel_model_download"; name: string; runtime?: RuntimeName }
  | { type: "cancel_all_model_downloads" }
  | { type: "remove_model"; name: string; runtime?: RuntimeName }
  | { type: "list_models" }
  | { type: "get_config" }
  | { type: "get_config_file" }
  | { type: "copy_text"; text: string }
  | { type: "set_welcome_shown" }
  | { type: "get_capabilities" };

// Server -> Client messages
export type ServerMessage =
  | { type: "status"; status: AppStatus; message: string; elapsed?: number }
  | { type: "transcript"; id?: number; timestamp: string; text: string; created_at?: string }
  | { type: "transcript_history"; entries: TranscriptEntry[] }
  | { type: "models"; models: ModelInfo[] }
  | { type: "config"; config: AppConfig }
  | { type: "hotkey_press" }
  | { type: "hotkey_release" }
  | { type: "error"; message: string }
  | { type: "config_file"; content: string; path: string }
  | {
      type: "toast";
      message: string;
      level?: "info" | "error";
      model?: string;
      runtime?: RuntimeName;
      action?:
        | "download_cancelled"
        | "download_failed"
        | "download_complete"
        | "remove_complete"
        | "remove_failed";
    }
  | { type: "log"; level: string; message: string; timestamp: string; source: string }
  | { type: "suppress_paste_input"; duration_ms?: number }
  | { type: "download_progress"; model: string; runtime: RuntimeName; percent: number }
  | {
      type: "runtime_switch_requires_model_variant";
      runtime: RuntimeName;
      model: string;
      format: string;
    }
  | { type: "capabilities"; capabilities: RuntimeCapabilities; recommended: { runtime: string; device: string } };

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

export type DialogType =
  | "model-manager"
  | "settings"
  | "settings-select"
  | "settings-edit"
  | "hotkey"
  | "theme-picker"
  | "exit-confirm"
  | "runtime-switch-confirm"
  | "welcome";

export type SelectSettingId =
  | "model.runtime"
  | "model.device"
  | "model.compute"
  | "model.language"
  | "audio.input_device"
  | "audio.sample_rate"
  | "vad.aggressiveness";

export interface ModelManagerDialogData {
  returnToSettings?: boolean;
  returnSettingId?: string;
  returnFilterQuery?: string;
  firstRunSetup?: boolean;
  pendingRuntimeSwitch?: {
    runtime: RuntimeName;
    model: string;
    format: string;
  };
}

export interface WelcomeDialogData {
  firstRun?: boolean;
  resumeStepIndex?: number;
  resumeModelIndex?: number;
  recommendationAutoApplied?: boolean;
}

export interface SettingsSelectDialogData {
  settingId: SelectSettingId;
  returnToSettings?: boolean;
  returnSettingId?: string;
  returnFilterQuery?: string;
  returnToDialog?: "welcome";
  returnWelcomeData?: WelcomeDialogData;
}

export interface ExitConfirmDialogData {
  model?: string;
  runtime?: RuntimeName;
}

export interface RuntimeSwitchConfirmDialogData {
  runtime: RuntimeName;
  model: string;
  format: string;
}

export interface DialogState {
  type: DialogType;
  data?: unknown;
}
