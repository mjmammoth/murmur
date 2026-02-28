import { describe, expect, test } from "bun:test";
import type { TranscriptEntry } from "../types";
import { mergeAndDedupeTranscripts } from "./transcriber-merge";

describe("mergeAndDedupeTranscripts", () => {
  test("dedupes hydrated history entry against live timestamp-only entry", () => {
    const liveEntry: TranscriptEntry = {
      timestamp: "12:00:00",
      text: "hello",
    };
    const hydratedEntry: TranscriptEntry = {
      id: 42,
      timestamp: "12:00:00",
      text: "hello",
      created_at: "2026-02-25T10:00:00Z",
    };

    const merged = mergeAndDedupeTranscripts([hydratedEntry], [liveEntry]);

    expect(merged.length).toBe(1);
    expect(merged[0]).toEqual(hydratedEntry);
  });

  test("dedupes entries when ids match but timestamps differ", () => {
    const first: TranscriptEntry = {
      id: 9,
      timestamp: "12:00:00",
      text: "first",
    };
    const second: TranscriptEntry = {
      id: 9,
      timestamp: "12:00:01",
      text: "second",
    };

    const merged = mergeAndDedupeTranscripts([first], [second]);

    expect(merged.length).toBe(1);
    expect(merged[0]).toEqual(first);
  });

  test("dedupes entries when timestamps match but ids differ", () => {
    const first: TranscriptEntry = {
      id: 10,
      timestamp: "12:00:02",
      text: "alpha",
    };
    const second: TranscriptEntry = {
      id: 11,
      timestamp: "12:00:02",
      text: "beta",
    };

    const merged = mergeAndDedupeTranscripts([first], [second]);

    expect(merged.length).toBe(1);
    expect(merged[0]).toEqual(first);
  });
});
