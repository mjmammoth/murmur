import { beforeEach, describe, expect, mock, test } from "bun:test";
import type { KeyEvent } from "@opentui/core";
import { createRoot } from "solid-js";

type ActiveModelOp = {
  type: "pulling" | "removing";
  model: string;
  runtime: string;
} | null;

type DownloadProgress = {
  model: string;
  runtime: string;
  percent: number;
} | null;

type JsxNode = {
  type: unknown;
  props?: {
    children?: unknown;
  };
};

const rendererToken = { name: "renderer" };
const closeDialog = mock(() => {});
const cancelAllModelDownloads = mock(() => {});
const registerDismissHandler = mock(() => () => {});
const exitApp = mock(() => {});

const state: {
  dialogData: { model?: string; runtime?: string };
  dialogType: string | null;
  activeModelOp: ActiveModelOp;
  progress: DownloadProgress;
  configRuntime: string;
} = {
  dialogData: {},
  dialogType: "exit-confirm",
  activeModelOp: null,
  progress: null,
  configRuntime: "faster-whisper",
};

let capturedKeyHandler: ((key: KeyEvent) => void) | null = null;

const jsxRuntimeStub = {
  Fragment: Symbol.for("Fragment"),
  jsx(type: unknown, props: Record<string, unknown> | null) {
    return { type, props: props ?? {} };
  },
  jsxs(type: unknown, props: Record<string, unknown> | null) {
    return { type, props: props ?? {} };
  },
  jsxDEV(type: unknown, props: Record<string, unknown> | null) {
    return { type, props: props ?? {} };
  },
};

mock.module("@opentui/solid/jsx-runtime", () => jsxRuntimeStub);
mock.module("@opentui/solid/jsx-dev-runtime", () => jsxRuntimeStub);
mock.module("@opentui/solid", () => ({
  useKeyHandler: (handler: (key: KeyEvent) => void) => {
    capturedKeyHandler = handler;
  },
  useRenderer: () => rendererToken,
}));

mock.module("../context/theme", () => ({
  useTheme: () => ({
    colors: () => ({
      backgroundPanel: "#000000",
      borderSubtle: "#333333",
      warning: "#ff9900",
      textMuted: "#999999",
      text: "#ffffff",
      textDim: "#777777",
      error: "#ff4444",
      selectedText: "#111111",
      accent: "#44aaff",
    }),
  }),
}));

mock.module("../context/dialog", () => ({
  useDialog: () => ({
    currentDialog: () => (state.dialogType ? { type: state.dialogType, data: state.dialogData } : null),
    closeDialog,
    registerDismissHandler,
  }),
}));

mock.module("../context/backend", () => ({
  useBackend: () => ({
    activeModelOp: () => state.activeModelOp,
    downloadProgress: () => state.progress,
    config: () => ({ model: { runtime: state.configRuntime } }),
    cancelAllModelDownloads,
  }),
}));

mock.module("../util/exit", () => ({ exitApp }));

const { ExitConfirmModal } = await import("./exit-confirm-modal");

beforeEach(() => {
  state.dialogData = {};
  state.dialogType = "exit-confirm";
  state.activeModelOp = null;
  state.progress = null;
  state.configRuntime = "faster-whisper";
  capturedKeyHandler = null;
  closeDialog.mockClear();
  cancelAllModelDownloads.mockClear();
  registerDismissHandler.mockClear();
  exitApp.mockClear();
});

function collectText(node: unknown): string[] {
  if (node === null || node === undefined || typeof node === "boolean") {
    return [];
  }
  if (typeof node === "string" || typeof node === "number") {
    return [String(node)];
  }
  if (Array.isArray(node)) {
    return node.flatMap((item) => collectText(item));
  }
  const maybeNode = node as JsxNode;
  if (maybeNode.props && "children" in maybeNode.props) {
    return collectText(maybeNode.props.children);
  }
  return [];
}

function renderModalText(): string {
  return createRoot((dispose) => {
    const tree = ExitConfirmModal();
    const text = collectText(tree).join(" ");
    dispose();
    return text;
  });
}

function dispatchKey(name: string, overrides: Partial<KeyEvent> = {}): void {
  if (!capturedKeyHandler) {
    throw new Error("Key handler was not registered");
  }
  const keyEvent = {
    name,
    eventType: "press",
    repeated: false,
    ctrl: false,
    shift: false,
    meta: false,
    option: false,
    preventDefault: mock(() => {}),
    ...overrides,
  } as unknown as KeyEvent;
  capturedKeyHandler(keyEvent);
}

describe("ExitConfirmModal", () => {
  test("renders warning text and active download progress", () => {
    state.dialogData = { model: "whisper-large", runtime: "faster-whisper" };
    state.progress = { model: "whisper-large", runtime: "faster-whisper", percent: 45.7 };

    const renderedText = renderModalText();

    expect(renderedText).toContain("Download in progress");
    expect(renderedText).toContain("whisper-large");
    expect(renderedText).toContain("faster-whisper");
    expect(renderedText).toContain("45% downloaded");
    expect(renderedText).toContain("Exit now to cancel the download and clean up incomplete files?");
    expect(registerDismissHandler).toHaveBeenCalledWith("exit-confirm", expect.any(Function));
  });

  test("uses active operation model when dialog data is empty", () => {
    state.activeModelOp = {
      type: "pulling",
      model: "whisper-small",
      runtime: "whisper.cpp",
    };
    state.progress = { model: "whisper-small", runtime: "whisper.cpp", percent: 88.2 };

    const renderedText = renderModalText();

    expect(renderedText).toContain("whisper-small");
    expect(renderedText).toContain("whisper.cpp");
    expect(renderedText).toContain("88% downloaded");
  });

  test("escape closes the dialog without exiting", () => {
    renderModalText();
    dispatchKey("escape");

    expect(closeDialog).toHaveBeenCalledTimes(1);
    expect(cancelAllModelDownloads).not.toHaveBeenCalled();
    expect(exitApp).not.toHaveBeenCalled();
  });

  test("confirm keys cancel downloads and exit", () => {
    renderModalText();

    dispatchKey("return");
    dispatchKey("y");
    dispatchKey("q");
    dispatchKey("c", { ctrl: true });

    expect(cancelAllModelDownloads).toHaveBeenCalledTimes(4);
    expect(exitApp).toHaveBeenCalledTimes(4);
    expect(exitApp).toHaveBeenCalledWith(rendererToken);
  });

  test("ignores release and repeated key events", () => {
    renderModalText();

    dispatchKey("escape", { eventType: "release" as KeyEvent["eventType"] });
    dispatchKey("y", { repeated: true });

    expect(closeDialog).not.toHaveBeenCalled();
    expect(cancelAllModelDownloads).not.toHaveBeenCalled();
    expect(exitApp).not.toHaveBeenCalled();
  });
});
