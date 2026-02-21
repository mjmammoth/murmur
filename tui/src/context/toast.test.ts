import { describe, expect, test } from "bun:test";
import {
  TOAST_LOG_DEDUPE_WINDOW_MS,
  shouldLogToast,
  shouldMirrorToastLog,
  toastLogDedupeKey,
} from "./toast-log";

describe("toastLogDedupeKey", () => {
  test("should use message when dedupe key is missing", () => {
    const key = toastLogDedupeKey("info", "Hello");
    expect(key).toBe("info|Hello|ui.toast");
  });

  test("should use dedupe key and source when provided", () => {
    const key = toastLogDedupeKey("error", "Ignored", {
      dedupeKey: "network-failure",
      source: "home.route",
    });
    expect(key).toBe("error|network-failure|home.route");
  });
});

describe("shouldLogToast", () => {
  test("should default to true", () => {
    expect(shouldLogToast()).toBe(true);
  });

  test("should disable logging when meta.log is false", () => {
    expect(shouldLogToast({ log: false })).toBe(false);
  });
});

describe("shouldMirrorToastLog", () => {
  test("should allow first log for dedupe key", () => {
    const cache = new Map<string, number>();
    expect(shouldMirrorToastLog(cache, "k", 1000)).toBe(true);
  });

  test("should suppress repeated logs inside dedupe window", () => {
    const cache = new Map<string, number>();
    expect(shouldMirrorToastLog(cache, "k", 1000)).toBe(true);
    expect(shouldMirrorToastLog(cache, "k", 1000 + TOAST_LOG_DEDUPE_WINDOW_MS - 1)).toBe(false);
  });

  test("should allow repeated logs after dedupe window", () => {
    const cache = new Map<string, number>();
    expect(shouldMirrorToastLog(cache, "k", 1000)).toBe(true);
    expect(shouldMirrorToastLog(cache, "k", 1000 + TOAST_LOG_DEDUPE_WINDOW_MS)).toBe(true);
  });
});
