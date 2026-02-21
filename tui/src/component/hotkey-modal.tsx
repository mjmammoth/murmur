import { createMemo, createSignal, onCleanup, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import { type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useBackend } from "../context/backend";
import { useConfig } from "../context/config";

const MODIFIER_KEYS = new Set(["shift", "ctrl", "control", "meta", "cmd", "command", "alt", "option"]);
const SHIFTED_DIGIT_SYMBOL_TO_KEY: Record<string, string> = {
  "!": "1",
  "@": "2",
  "#": "3",
  "$": "4",
  "%": "5",
  "^": "6",
  "&": "7",
  "*": "8",
  "(": "9",
  ")": "0",
};

function normalizeHotkeyBaseKey(name: string): { baseKey: string | null; inferredShift: boolean } {
  if (SHIFTED_DIGIT_SYMBOL_TO_KEY[name]) {
    return { baseKey: SHIFTED_DIGIT_SYMBOL_TO_KEY[name]!, inferredShift: true };
  }

  const lowered = name.toLowerCase();
  if (/^[a-z0-9]$/.test(lowered)) return { baseKey: lowered, inferredShift: false };
  if (/^f([1-9]|1[0-2])$/.test(lowered)) return { baseKey: lowered, inferredShift: false };

  switch (lowered) {
    case "space":
      return { baseKey: "space", inferredShift: false };
    case "return":
    case "enter":
      return { baseKey: "return", inferredShift: false };
    case "tab":
      return { baseKey: "tab", inferredShift: false };
    case "escape":
    case "esc":
      return { baseKey: "escape", inferredShift: false };
    default:
      return { baseKey: null, inferredShift: false };
  }
}

function formatHotkeyFromEvent(key: KeyEvent): { hotkey: string | null; error?: string; modifierOnly?: boolean } {
  const caseInferredShift = key.name.length === 1 && key.name !== key.name.toLowerCase();
  const name = key.name.toLowerCase();
  if (MODIFIER_KEYS.has(name)) return { hotkey: null, modifierOnly: true };

  const { baseKey, inferredShift } = normalizeHotkeyBaseKey(key.name);
  const hasShift = key.shift || caseInferredShift || inferredShift;
  if (!baseKey) {
    return { hotkey: null, error: `Unsupported key: ${key.name}` };
  }

  const parts: string[] = [];
  if (key.meta) parts.push("cmd");
  if (key.ctrl) parts.push("ctrl");
  if (key.option) parts.push("option");
  if (hasShift) parts.push("shift");
  parts.push(baseKey);

  return { hotkey: parts.join("+") };
}

export function HotkeyModal(): JSX.Element {
  const { colors } = useTheme();
  const dialog = useDialog();
  const backend = useBackend();
  const config = useConfig();
  const [captureError, setCaptureError] = createSignal("");
  const [lastSetHotkey, setLastSetHotkey] = createSignal("");

  const dialogData = createMemo(
    () =>
      (dialog.currentDialog()?.data as {
        returnToSettings?: boolean;
        returnSettingId?: string;
        returnFilterQuery?: string;
      } | undefined) ??
      undefined,
  );
  const returnToSettings = createMemo(() => Boolean(dialogData()?.returnToSettings));
  const returnSettingId = createMemo(() => dialogData()?.returnSettingId ?? null);
  const returnFilterQuery = createMemo(() => dialogData()?.returnFilterQuery ?? null);

  function closeModal() {
    if (returnToSettings()) {
      const selectedSettingId = returnSettingId();
      const filterQuery = returnFilterQuery();
      dialog.openDialog(
        "settings",
        selectedSettingId || filterQuery
          ? { selectedSettingId: selectedSettingId ?? undefined, filterQuery: filterQuery ?? undefined }
          : undefined,
      );
      return;
    }
    dialog.closeDialog();
  }

  const unregisterDismissHandler = dialog.registerDismissHandler("hotkey", closeModal);
  onCleanup(unregisterDismissHandler);

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "hotkey") return;
    if (key.eventType === "release" || key.repeated) return;

    key.preventDefault();

    if (key.name === "escape" || key.name === "q") {
      closeModal();
      return;
    }

    const parsed = formatHotkeyFromEvent(key);
    if (parsed.modifierOnly) {
      setCaptureError("Press a non-modifier key");
      return;
    }
    if (parsed.error || !parsed.hotkey) {
      setCaptureError(parsed.error ?? "Unsupported key");
      return;
    }

    backend.send({ type: "set_hotkey", hotkey: parsed.hotkey });
    setLastSetHotkey(parsed.hotkey);
    setCaptureError("");
  });

  return (
    <box
      flexDirection="column"
      width={58}
      backgroundColor={colors().backgroundPanel}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} paddingBottom={0} flexDirection="column">
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Hotkey</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>press combo</span>
            </text>
            <box backgroundColor={colors().error} paddingX={1} onMouseUp={closeModal}>
              <text>
                <span style={{ fg: colors().selectedText }}>esc/q</span>
              </text>
            </box>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().secondary} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <box paddingX={3} paddingBottom={1}>
        <text>
          <span style={{ fg: colors().textDim }}>current: </span>
          <span style={{ fg: colors().text }}>{config.config()?.hotkey.key ?? "-"}</span>
        </text>
      </box>

      <box paddingX={3} paddingBottom={1}>
        <text>
          <span style={{ fg: colors().warning }}>listening...</span>
          <span style={{ fg: colors().textMuted }}> press new combo now</span>
        </text>
      </box>

      <box paddingX={3}>
        <text>
          <span style={{ fg: captureError() ? colors().error : colors().textDim }}>
            {captureError() || (lastSetHotkey() ? `set to ${lastSetHotkey()}` : "esc/q cancel")}
          </span>
        </text>
      </box>
    </box>
  );
}
