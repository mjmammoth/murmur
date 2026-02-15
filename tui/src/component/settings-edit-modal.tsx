import { createEffect, createMemo, createSignal, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";
import { useConfig } from "../context/config";

type EditSettingId = "model.path" | "output.file.path";

interface SettingsEditDialogData {
  settingId: EditSettingId;
  returnToSettings?: boolean;
  returnSettingId?: string;
}

function isPrintableKey(key: KeyEvent): boolean {
  if (key.ctrl || key.meta || key.option) return false;
  return key.name.length === 1;
}

export function SettingsEditModal(): JSX.Element {
  const { colors } = useTheme();
  const dialog = useDialog();
  const config = useConfig();

  const [draft, setDraft] = createSignal("");
  const [error, setError] = createSignal("");

  const dialogData = createMemo(
    () => (dialog.currentDialog()?.data as SettingsEditDialogData | undefined) ?? null,
  );
  const settingId = createMemo<EditSettingId | null>(() => dialogData()?.settingId ?? null);
  const returnToSettings = createMemo(() => Boolean(dialogData()?.returnToSettings));
  const returnSettingId = createMemo(() => dialogData()?.returnSettingId ?? null);

  const title = createMemo(() => {
    switch (settingId()) {
      case "model.path":
        return "Local Model Path";
      case "output.file.path":
        return "Output File Path";
      default:
        return "Edit Value";
    }
  });

  const subtitle = createMemo(() => {
    switch (settingId()) {
      case "model.path":
        return "set local override or leave empty for default cache";
      case "output.file.path":
        return "set transcript append destination path";
      default:
        return "edit setting value";
    }
  });

  const placeholder = createMemo(() => {
    switch (settingId()) {
      case "model.path":
        return "empty = default cache";
      case "output.file.path":
        return "~/transcripts.txt";
      default:
        return "";
    }
  });

  createEffect(() => {
    if (dialog.currentDialog()?.type !== "settings-edit") return;
    setError("");
    switch (settingId()) {
      case "model.path":
        setDraft(config.config()?.model.path ?? "");
        return;
      case "output.file.path":
        setDraft(config.config()?.output.file.path ?? "");
        return;
      default:
        setDraft("");
    }
  });

  function closeModal() {
    if (returnToSettings()) {
      const selectedSettingId = returnSettingId();
      dialog.openDialog(
        "settings",
        selectedSettingId ? { selectedSettingId } : undefined,
      );
      return;
    }
    dialog.closeDialog();
  }

  function applyValue() {
    const trimmed = draft().trim();
    setError("");

    switch (settingId()) {
      case "model.path":
        config.setModelPath(trimmed.length > 0 ? trimmed : null);
        closeModal();
        return;
      case "output.file.path":
        if (trimmed.length === 0) {
          setError("Path cannot be empty");
          return;
        }
        config.setOutputFilePath(trimmed);
        closeModal();
        return;
      default:
        return;
    }
  }

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings-edit") return;
    if (key.eventType === "release") return;

    switch (key.name) {
      case "escape":
        key.preventDefault();
        closeModal();
        return;
      case "return":
      case "enter":
        key.preventDefault();
        applyValue();
        return;
      case "backspace":
        key.preventDefault();
        setDraft((prev) => prev.slice(0, -1));
        setError("");
        return;
      case "space":
        key.preventDefault();
        setDraft((prev) => `${prev} `);
        setError("");
        return;
      default:
        if (!isPrintableKey(key)) return;
        key.preventDefault();
        setDraft((prev) => `${prev}${key.name}`);
        setError("");
    }
  });

  return (
    <box
      flexDirection="column"
      width={82}
      backgroundColor={colors().backgroundPanel}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} paddingBottom={0} flexDirection="column">
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>{title()}</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>{subtitle()}</span>
            </text>
            <box backgroundColor={colors().secondary} paddingX={1}>
              <text>
                <span style={{ fg: colors().selectedText }}>esc</span>
              </text>
            </box>
          </box>
        </box>
        <box flexDirection="row" width="100%" marginTop={0}>
          <box width={3} borderStyle="single" border={["bottom"]} borderColor={colors().secondary} />
          <box flexGrow={1} borderStyle="single" border={["bottom"]} borderColor={colors().borderSubtle} />
        </box>
      </box>

      <box paddingX={3} paddingTop={1}>
        <box
          width="100%"
          backgroundColor={colors().backgroundElement}
          borderStyle="single"
          borderColor={error() ? colors().error : colors().borderSubtle}
          paddingX={1}
          paddingY={0}
        >
          <text>
            <span style={{ fg: draft() ? colors().text : colors().textDim }}>
              {draft() || placeholder()}
            </span>
            <span style={{ fg: colors().secondary }}>|</span>
          </text>
        </box>
      </box>

      <box paddingX={3} paddingTop={1}>
        <text>
          <span style={{ fg: error() ? colors().error : colors().textDim }}>
            {error() || "Type value, enter to apply, esc to cancel"}
          </span>
        </text>
      </box>
    </box>
  );
}
