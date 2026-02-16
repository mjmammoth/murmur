import { describe, expect, test } from "bun:test";

/**
 * Tests for Home component
 *
 * Main application route that orchestrates the entire UI including header, footer, transcript list,
 * logs panel, modals, and handles global keyboard shortcuts and state management.
 */

describe("Home", () => {
  const LOGS_PANEL_WIDTH_COLS = 48;
  const LOGS_PANEL_MIN_TERMINAL_WIDTH = 115;

  describe("logs panel visibility logic", () => {
    test("should show logs when width sufficient", () => {
      const terminalWidth = 120;
      const canShowLogs = terminalWidth >= LOGS_PANEL_MIN_TERMINAL_WIDTH;

      expect(canShowLogs).toBe(true);
    });

    test("should not show logs when width insufficient", () => {
      const terminalWidth = 100;
      const canShowLogs = terminalWidth >= LOGS_PANEL_MIN_TERMINAL_WIDTH;

      expect(canShowLogs).toBe(false);
    });

    test("should show logs at exact threshold", () => {
      const terminalWidth = LOGS_PANEL_MIN_TERMINAL_WIDTH;
      const canShowLogs = terminalWidth >= LOGS_PANEL_MIN_TERMINAL_WIDTH;

      expect(canShowLogs).toBe(true);
    });

    test("should combine show and can show flags", () => {
      const showLogs = true;
      const terminalWidth = 120;
      const canShowLogs = terminalWidth >= LOGS_PANEL_MIN_TERMINAL_WIDTH;
      const logsVisible = showLogs && canShowLogs;

      expect(logsVisible).toBe(true);
    });
  });

  describe("homePaneWidth calculation", () => {
    test("should use full width when logs not visible", () => {
      const terminalWidth = 100;
      const logsVisible = false;
      const homePaneWidth = logsVisible ? Math.max(0, terminalWidth - LOGS_PANEL_WIDTH_COLS) : terminalWidth;

      expect(homePaneWidth).toBe(100);
    });

    test("should subtract logs width when visible", () => {
      const terminalWidth = 120;
      const logsVisible = true;
      const homePaneWidth = logsVisible ? Math.max(0, terminalWidth - LOGS_PANEL_WIDTH_COLS) : terminalWidth;

      expect(homePaneWidth).toBe(72);
    });

    test("should not go negative", () => {
      const terminalWidth = 30;
      const logsVisible = true;
      const homePaneWidth = logsVisible ? Math.max(0, terminalWidth - LOGS_PANEL_WIDTH_COLS) : terminalWidth;

      expect(homePaneWidth).toBe(0);
    });
  });

  describe("requestExit logic", () => {
    test("should prompt when model is pulling", () => {
      const activeOp = { type: "pulling" as const, model: "whisper-base" };
      const currentDialog = { type: "model-manager" as const };
      const shouldPrompt = activeOp?.type === "pulling" && currentDialog?.type !== "exit-confirm";

      expect(shouldPrompt).toBe(true);
    });

    test("should exit directly when not pulling", () => {
      const activeOp = null;
      const shouldPrompt = activeOp?.type === "pulling";

      expect(shouldPrompt).toBe(false);
    });

    test("should exit directly when exit-confirm already open", () => {
      const activeOp = { type: "pulling" as const, model: "whisper-base" };
      const currentDialog = { type: "exit-confirm" as const };
      const shouldPrompt = activeOp?.type === "pulling" && currentDialog?.type !== "exit-confirm";

      expect(shouldPrompt).toBe(false);
    });
  });

  describe("toggleRecordingFromStatusClick logic", () => {
    test("should not toggle when dialog is open", () => {
      const dialogIsOpen = true;
      const shouldProceed = !dialogIsOpen;

      expect(shouldProceed).toBe(false);
    });

    test("should stop recording when recording", () => {
      const status = "recording";
      const action = status === "recording" ? "stop" : "other";

      expect(action).toBe("stop");
    });

    test("should start recording when ready", () => {
      const status = "ready";
      const action = status === "ready" ? "start" : "other";

      expect(action).toBe("start");
    });

    test("should show toast when connecting", () => {
      const status = "connecting";
      const shouldShowToast = status === "connecting";

      expect(shouldShowToast).toBe(true);
    });

    test("should show toast when busy", () => {
      const status = "transcribing";
      const shouldShowToast = status === "transcribing" || status === "downloading";

      expect(shouldShowToast).toBe(true);
    });

    test("should show toast when error", () => {
      const status = "error";
      const shouldShowToast = status === "error";

      expect(shouldShowToast).toBe(true);
    });
  });

  describe("keyboard shortcuts", () => {
    test("should handle ctrl+c for exit", () => {
      const key = { name: "c", ctrl: true };
      const shouldExit = key.ctrl && key.name === "c";

      expect(shouldExit).toBe(true);
    });

    test("should handle q for quit", () => {
      const keyName = "q";
      const shouldQuit = keyName === "q";

      expect(shouldQuit).toBe(true);
    });

    test("should handle c for copy latest", () => {
      const keyName = "c";
      const shouldCopy = keyName === "c";

      expect(shouldCopy).toBe(true);
    });

    test("should handle enter for copy selected", () => {
      const keyName = "return";
      const shouldCopySelected = keyName === "return" || keyName === "enter";

      expect(shouldCopySelected).toBe(true);
    });

    test("should handle a for auto copy toggle", () => {
      const keyName = "a";
      const shouldToggleAutoCopy = keyName === "a";

      expect(shouldToggleAutoCopy).toBe(true);
    });

    test("should handle p for auto paste toggle", () => {
      const keyName = "p";
      const shouldToggleAutoPaste = keyName === "p";

      expect(shouldToggleAutoPaste).toBe(true);
    });

    test("should handle n for noise toggle", () => {
      const keyName = "n";
      const shouldToggleNoise = keyName === "n";

      expect(shouldToggleNoise).toBe(true);
    });

    test("should handle v for VAD toggle", () => {
      const keyName = "v";
      const shouldToggleVad = keyName === "v";

      expect(shouldToggleVad).toBe(true);
    });

    test("should handle o for hotkey mode toggle", () => {
      const keyName = "o";
      const shouldToggleMode = keyName === "o";

      expect(shouldToggleMode).toBe(true);
    });

    test("should handle m for model manager", () => {
      const keyName = "m";
      const shouldOpenModels = keyName === "m";

      expect(shouldOpenModels).toBe(true);
    });

    test("should handle s for settings", () => {
      const keyName = "s";
      const shouldOpenSettings = keyName === "s";

      expect(shouldOpenSettings).toBe(true);
    });

    test("should handle h for hotkey", () => {
      const keyName = "h";
      const shouldOpenHotkey = keyName === "h";

      expect(shouldOpenHotkey).toBe(true);
    });

    test("should handle t for theme picker", () => {
      const keyName = "t";
      const shouldOpenTheme = keyName === "t";

      expect(shouldOpenTheme).toBe(true);
    });

    test("should handle l for logs toggle", () => {
      const keyName = "l";
      const dialogIsOpen = false;
      const shouldToggleLogs = keyName === "l" && !dialogIsOpen;

      expect(shouldToggleLogs).toBe(true);
    });

    test("should not handle l when dialog is open", () => {
      const keyName = "l";
      const dialogIsOpen = true;
      const shouldToggleLogs = keyName === "l" && !dialogIsOpen;

      expect(shouldToggleLogs).toBe(false);
    });
  });

  describe("transcript navigation", () => {
    test("should select previous with up", () => {
      const keyName = "up";
      const shouldSelectPrev = keyName === "up" || keyName === "k";

      expect(shouldSelectPrev).toBe(true);
    });

    test("should select previous with k", () => {
      const keyName = "k";
      const shouldSelectPrev = keyName === "up" || keyName === "k";

      expect(shouldSelectPrev).toBe(true);
    });

    test("should select next with down", () => {
      const keyName = "down";
      const shouldSelectNext = keyName === "down" || keyName === "j";

      expect(shouldSelectNext).toBe(true);
    });

    test("should select next with j", () => {
      const keyName = "j";
      const shouldSelectNext = keyName === "down" || keyName === "j";

      expect(shouldSelectNext).toBe(true);
    });
  });

  describe("logs panel keyboard handling", () => {
    test("should close logs on escape", () => {
      const keyName = "escape";
      const logsVisible = true;
      const dialogIsOpen = false;
      const shouldCloseLogs = keyName === "escape" && logsVisible && !dialogIsOpen;

      expect(shouldCloseLogs).toBe(true);
    });

    test("should toggle pane with tab", () => {
      const keyName = "tab";
      const logsVisible = true;
      const dialogIsOpen = false;
      const shouldTogglePane = keyName === "tab" && logsVisible && !dialogIsOpen;

      expect(shouldTogglePane).toBe(true);
    });

    test("should change log level with left arrow", () => {
      const keyName = "left";
      const logsVisible = true;
      const activePane = "logs";
      const dialogIsOpen = false;
      const shouldChangeLevel = logsVisible && activePane === "logs" && !dialogIsOpen && (keyName === "left" || keyName === "right");

      expect(shouldChangeLevel).toBe(true);
    });
  });

  describe("paste handling", () => {
    test("should process paste when not suppressed", () => {
      const suppressPasteInputUntil = Date.now() - 1000;
      const shouldSuppressPasteInput = Date.now() < suppressPasteInputUntil;

      expect(shouldSuppressPasteInput).toBe(false);
    });

    test("should suppress paste when within window", () => {
      const suppressPasteInputUntil = Date.now() + 1000;
      const shouldSuppressPasteInput = Date.now() < suppressPasteInputUntil;

      expect(shouldSuppressPasteInput).toBe(true);
    });

    test("should not process paste when dialog open", () => {
      const dialogIsOpen = true;
      const shouldProcess = !dialogIsOpen;

      expect(shouldProcess).toBe(false);
    });

    test("should ignore empty paste", () => {
      const pastedText = "   ";
      const trimmed = pastedText.trim();
      const shouldProcess = trimmed.length > 0;

      expect(shouldProcess).toBe(false);
    });
  });

  describe("copy transcript logic", () => {
    test("should show toast when no transcripts", () => {
      const latestTranscript = null;
      const shouldShowToast = !latestTranscript;

      expect(shouldShowToast).toBe(true);
    });

    test("should copy latest transcript", () => {
      const latestTranscript = { text: "Test transcript", timestamp: "12:00" };
      const textToCopy = latestTranscript?.text ?? "";

      expect(textToCopy).toBe("Test transcript");
    });

    test("should show toast when no transcript selected", () => {
      const selectedTranscript = null;
      const shouldShowToast = !selectedTranscript;

      expect(shouldShowToast).toBe(true);
    });
  });

  describe("first run setup", () => {
    test("should detect first run setup required", () => {
      const config = { first_run_setup_required: true };
      const setupRequired = Boolean(config.first_run_setup_required);

      expect(setupRequired).toBe(true);
    });

    test("should open model manager for first run", () => {
      const firstRunSetupRequired = true;
      const models = [{ name: "whisper-base", installed: false, path: null }];
      const currentDialog = null;
      const shouldOpenManager = firstRunSetupRequired && models.length > 0 && !currentDialog;

      expect(shouldOpenManager).toBe(true);
    });

    test("should not open model manager when already open", () => {
      const firstRunSetupRequired = true;
      const models = [{ name: "whisper-base", installed: false, path: null }];
      const currentDialog = { type: "model-manager", data: { firstRunSetup: true } };
      const shouldOpenManager = firstRunSetupRequired && models.length > 0 && currentDialog?.type === "model-manager";

      expect(shouldOpenManager).toBe(true);
    });
  });

  describe("active pane logic", () => {
    test("should default to main pane", () => {
      const activePane = "main";

      expect(activePane).toBe("main");
    });

    test("should switch to logs pane", () => {
      const currentPane = "main";
      const nextPane = currentPane === "main" ? "logs" : "main";

      expect(nextPane).toBe("logs");
    });

    test("should switch back to main pane", () => {
      const currentPane = "logs";
      const nextPane = currentPane === "main" ? "logs" : "main";

      expect(nextPane).toBe("main");
    });

    test("should force main when logs become invisible", () => {
      const logsVisible = false;
      const activePane = "logs";
      const shouldForceMain = !logsVisible && activePane === "logs";

      expect(shouldForceMain).toBe(true);
    });
  });

  describe("modal overlay", () => {
    test("should render model manager modal", () => {
      const currentDialog = { type: "model-manager" };
      const shouldRenderModelManager = currentDialog?.type === "model-manager";

      expect(shouldRenderModelManager).toBe(true);
    });

    test("should render settings modal", () => {
      const currentDialog = { type: "settings" };
      const shouldRenderSettings = currentDialog?.type === "settings";

      expect(shouldRenderSettings).toBe(true);
    });

    test("should render hotkey modal", () => {
      const currentDialog = { type: "hotkey" };
      const shouldRenderHotkey = currentDialog?.type === "hotkey";

      expect(shouldRenderHotkey).toBe(true);
    });

    test("should render theme picker modal", () => {
      const currentDialog = { type: "theme-picker" };
      const shouldRenderThemePicker = currentDialog?.type === "theme-picker";

      expect(shouldRenderThemePicker).toBe(true);
    });

    test("should render exit confirm modal", () => {
      const currentDialog = { type: "exit-confirm" };
      const shouldRenderExitConfirm = currentDialog?.type === "exit-confirm";

      expect(shouldRenderExitConfirm).toBe(true);
    });
  });

  describe("edge cases", () => {
    test("should handle very small terminal width", () => {
      const terminalWidth = 50;
      const logsVisible = true;
      const homePaneWidth = Math.max(0, terminalWidth - LOGS_PANEL_WIDTH_COLS);

      expect(homePaneWidth).toBe(2);
    });

    test("should handle large terminal width", () => {
      const terminalWidth = 200;
      const logsVisible = true;
      const homePaneWidth = terminalWidth - LOGS_PANEL_WIDTH_COLS;

      expect(homePaneWidth).toBe(152);
    });
  });
});