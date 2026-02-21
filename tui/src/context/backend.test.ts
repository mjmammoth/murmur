import { describe, expect, test } from "bun:test";
import type { LogEntry } from "../types";
import { appendLogWithLimit, formatClientLogTimestamp } from "./backend-log";

describe("appendLogWithLimit", () => {
  test("should append when under limit", () => {
    const prev: LogEntry[] = [
      { id: 1, level: "INFO", message: "one", timestamp: "12:00:00", source: "test" },
    ];
    const next = appendLogWithLimit(prev, {
      id: 2,
      level: "INFO",
      message: "two",
      timestamp: "12:00:01",
      source: "test",
    });

    expect(next.length).toBe(2);
    expect(next[1]?.message).toBe("two");
  });

  test("should keep last 200 entries", () => {
    const prev: LogEntry[] = Array.from({ length: 200 }, (_, idx) => ({
      id: idx,
      level: "INFO",
      message: `entry-${idx}`,
      timestamp: "12:00:00",
      source: "test",
    }));
    const next = appendLogWithLimit(prev, {
      id: 200,
      level: "INFO",
      message: "entry-200",
      timestamp: "12:00:01",
      source: "test",
    });

    expect(next.length).toBe(200);
    expect(next[0]?.message).toBe("entry-1");
    expect(next[199]?.message).toBe("entry-200");
  });
});

describe("formatClientLogTimestamp", () => {
  test("should format as HH:MM:SS", () => {
    const formatted = formatClientLogTimestamp(new Date("2026-01-02T03:04:05.000Z"));

    expect(formatted.length).toBe(8);
    expect(formatted.split(":").length).toBe(3);
  });
});
