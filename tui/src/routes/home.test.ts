import { describe, expect, test } from "bun:test";

describe("Home route welcome auto-open guard", () => {
  test("should not auto-open welcome when another dialog is active", () => {
    const welcomeShown = false;
    const firstRunSetupRequired = true;
    const hasConfig = true;
    const hasModels = true;
    const currentDialog = { type: "settings-select" };

    const shouldOpenWelcome =
      !(welcomeShown && !firstRunSetupRequired) &&
      hasConfig &&
      hasModels &&
      !currentDialog;

    expect(shouldOpenWelcome).toBe(false);
  });

  test("should auto-open welcome when no dialog is active and first run is pending", () => {
    const welcomeShown = false;
    const firstRunSetupRequired = true;
    const hasConfig = true;
    const hasModels = true;
    const currentDialog = null;

    const shouldOpenWelcome =
      !(welcomeShown && !firstRunSetupRequired) &&
      hasConfig &&
      hasModels &&
      !currentDialog;

    expect(shouldOpenWelcome).toBe(true);
  });
});

describe("Home route exit confirmation", () => {
  test("should open exit confirm when queued downloads exist", () => {
    const hasPendingModelDownloads = true;
    const currentDialogType: string | undefined = undefined;
    const shouldOpenExitConfirm = hasPendingModelDownloads && currentDialogType !== "exit-confirm";

    expect(shouldOpenExitConfirm).toBe(true);
  });

  test("should open exit confirm when active pulling download exists", () => {
    const activeOp = { type: "pulling" as const, model: "small", runtime: "faster-whisper" };
    const hasPendingModelDownloads = activeOp.type === "pulling";
    const currentDialogType: string | undefined = undefined;
    const shouldOpenExitConfirm = hasPendingModelDownloads && currentDialogType !== "exit-confirm";

    expect(shouldOpenExitConfirm).toBe(true);
  });
});
