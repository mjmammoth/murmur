import { createEffect, createMemo, createSignal, For, Show, type JSX } from "solid-js";
import { useKeyHandler, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent, ScrollBoxRenderable } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useDialog } from "../context/dialog";

interface ThemePickerDialogData {
  returnToSettings?: boolean;
  returnSettingId?: string;
  returnFilterQuery?: string;
}

export function ThemePickerModal(): JSX.Element {
  const { colors, themeId, availableThemes, setTheme, persistTheme } = useTheme();
  const dialog = useDialog();
  const terminal = useTerminalDimensions();

  const [selectedIndex, setSelectedIndex] = createSignal(0);
  const [initialThemeId, setInitialThemeId] = createSignal<string | null>(null);
  const [initializedForOpen, setInitializedForOpen] = createSignal(false);
  let themeScroll: ScrollBoxRenderable | undefined;

  const dialogData = createMemo(
    () => (dialog.currentDialog()?.data as ThemePickerDialogData | undefined) ?? null,
  );
  const returnToSettings = createMemo(() => Boolean(dialogData()?.returnToSettings));
  const returnSettingId = createMemo(() => dialogData()?.returnSettingId ?? null);
  const returnFilterQuery = createMemo(() => dialogData()?.returnFilterQuery ?? null);

  const selectedTheme = createMemo(() => availableThemes[selectedIndex()] ?? null);

  function getThemeById(id: string | null): string | null {
    if (!id) return null;
    return availableThemes.some((themeOption) => themeOption.id === id) ? id : null;
  }

  function defaultThemeId(): string | null {
    return getThemeById("dark") ?? availableThemes[0]?.id ?? null;
  }

  createEffect(() => {
    const isOpen = dialog.currentDialog()?.type === "theme-picker";
    if (!isOpen) {
      setInitializedForOpen(false);
      setInitialThemeId(null);
      return;
    }
    if (initializedForOpen()) return;

    setInitializedForOpen(true);
    const current = themeId();
    setInitialThemeId(current);
    const index = availableThemes.findIndex((theme) => theme.id === current);
    setSelectedIndex(index >= 0 ? index : 0);
  });

  function previewIndex(index: number) {
    if (availableThemes.length === 0) return;
    const next = Math.max(0, Math.min(index, availableThemes.length - 1));
    setSelectedIndex(next);
    const preview = availableThemes[next];
    if (preview) setTheme(preview.id);
  }

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

  function moveSelection(delta: number) {
    const count = availableThemes.length;
    if (count === 0) return;
    let next = selectedIndex() + delta;
    if (next < 0) next = count - 1;
    if (next >= count) next = 0;
    previewIndex(next);
  }

  function cancelSelection() {
    const initial = getThemeById(initialThemeId());
    if (initial) {
      setTheme(initial);
    } else {
      const fallback = getThemeById(defaultThemeId());
      if (fallback) setTheme(fallback);
    }
    closeModal();
  }

  function applySelection() {
    const selected = selectedTheme();
    if (!selected) return;
    persistTheme(selected.id);
    closeModal();
  }

  function badgeTextFor(themeOptionId: string, active: boolean): string {
    const labels: string[] = [];
    if (active) labels.push("active");
    if (themeOptionId === "dark") labels.push("default");
    return labels.join(" ");
  }

  createEffect(() => {
    if (dialog.currentDialog()?.type !== "theme-picker") return;
    if (!themeScroll || themeScroll.isDestroyed) return;
    const index = selectedIndex();
    const target = themeScroll.getChildren()[index];
    if (!target) return;

    const top = target.y - themeScroll.y;
    const bottom = top + Math.max(1, target.height) - 1;

    if (bottom >= themeScroll.height) {
      themeScroll.scrollBy(bottom - themeScroll.height + 1);
      return;
    }
    if (top < 0) {
      themeScroll.scrollBy(top);
    }
  });

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "theme-picker") return;
    if (key.eventType === "release") return;

    switch (key.name) {
      case "escape":
      case "q":
        key.preventDefault();
        cancelSelection();
        return;
      case "up":
      case "k":
        key.preventDefault();
        moveSelection(-1);
        return;
      case "down":
      case "j":
        key.preventDefault();
        moveSelection(1);
        return;
      case "return":
      case "enter":
        key.preventDefault();
        applySelection();
        return;
      default:
        return;
    }
  });

  const modalWidth = createMemo(() => {
    const maxWidth = Math.max(56, terminal().width - 8);
    const preferred = Math.floor(terminal().width * 0.56);
    return Math.max(56, Math.min(preferred, maxWidth));
  });

  const modalHeight = createMemo(() => {
    const maxHeight = Math.max(14, terminal().height - 6);
    const preferred = Math.floor(terminal().height * 0.55);
    return Math.max(14, Math.min(preferred, maxHeight));
  });

  return (
    <box
      flexDirection="column"
      width={modalWidth()}
      height={modalHeight()}
      backgroundColor={colors().backgroundPanel}
      paddingY={1}
    >
      <box paddingX={3} paddingTop={1} paddingBottom={0} flexDirection="column" flexShrink={0}>
        <box flexDirection="row" justifyContent="space-between" width="100%" alignItems="center">
          <text>
            <span style={{ fg: colors().primary, bold: true }}>Theme</span>
          </text>
          <box flexDirection="row" alignItems="center" gap={2}>
            <text>
              <span style={{ fg: colors().textMuted }}>live preview while navigating</span>
            </text>
            <box backgroundColor={colors().secondary} paddingX={1}>
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

      <box paddingX={3} paddingTop={1} flexShrink={0}>
        <text>
          <span style={{ fg: colors().textDim }}>preview: </span>
          <span style={{ fg: colors().text }}>{selectedTheme()?.label ?? "-"}</span>
        </text>
      </box>

      <scrollbox
        flexGrow={1}
        paddingTop={1}
        paddingBottom={1}
        ref={(renderable: ScrollBoxRenderable) => {
          themeScroll = renderable;
        }}
      >
        <Show
          when={availableThemes.length > 0}
          fallback={
            <box paddingX={3}>
              <text>
                <span style={{ fg: colors().textMuted }}>No themes available.</span>
              </text>
            </box>
          }
        >
          <For each={availableThemes}>
            {(themeOption, index) => {
              const isActive = () => index() === selectedIndex();
              const isCurrent = () => themeOption.id === themeId();
              const badgeText = () => badgeTextFor(themeOption.id, isCurrent());
              return (
                <box
                  role="option"
                  aria-selected={isActive()}
                  flexDirection="row"
                  paddingRight={1}
                  backgroundColor={isActive() ? colors().backgroundElement : undefined}
                  onMouseUp={() => previewIndex(index())}
                >
                  <box width={1} backgroundColor={isActive() ? colors().secondary : undefined} />
                  <box paddingLeft={2} paddingRight={1} paddingY={1} flexDirection="column" width="100%">
                    <box flexDirection="row" justifyContent="space-between" width="100%">
                      <text>
                        <span style={{ fg: colors().text, bold: true }}>{themeOption.label}</span>
                      </text>
                      <text>
                        <span style={{ fg: isCurrent() ? colors().success : colors().textDim }}>
                          {badgeText()}
                        </span>
                      </text>
                    </box>
                    <text>
                      <span style={{ fg: colors().textMuted }}>{themeOption.description}</span>
                    </text>
                    <box flexDirection="row" gap={2}>
                      <text>
                        <span style={{ fg: themeOption.colors?.primary ?? colors().primary }}>■■</span>
                      </text>
                      <text>
                        <span style={{ fg: themeOption.colors?.secondary ?? colors().secondary }}>■■</span>
                      </text>
                      <text>
                        <span style={{ fg: themeOption.colors?.accent ?? colors().accent }}>■■</span>
                      </text>
                      <text>
                        <span style={{ fg: themeOption.colors?.text ?? colors().text }}>text</span>
                      </text>
                      <text>
                        <span style={{ fg: themeOption.colors?.warning ?? colors().warning }}>warn</span>
                      </text>
                    </box>
                  </box>
                </box>
              );
            }}
          </For>
        </Show>
      </scrollbox>

      <box flexShrink={0} paddingX={3} paddingTop={1}>
        <box flexDirection="row" gap={2} alignItems="center">
          <text>
            <span style={{ fg: colors().textMuted }}>↑/↓ navigate</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>enter apply</span>
          </text>
          <text>
            <span style={{ fg: colors().textMuted }}>esc/q cancel</span>
          </text>
        </box>
      </box>
    </box>
  );
}
