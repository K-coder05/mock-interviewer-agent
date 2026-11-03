import { describe, expect, it } from "vitest";
import type { SessionEvent } from "./api";
import { clock, codeAt, runsAt, transcriptAt } from "./replay";

function ev(seq: number, t_ms: number, type: string, payload: Record<string, unknown>): SessionEvent {
  return { id: `e${seq}`, session_id: "s", seq, t_ms, type, payload };
}

const EVENTS = [
  ev(1, 0, "code_snapshot", { code: "# start\n" }),
  ev(2, 10_000, "utterance", { speaker: "interviewer", text: "Hello" }),
  ev(3, 20_000, "code_snapshot", { code: "x = 1\n" }),
  ev(4, 25_000, "utterance", { speaker: "user", text: "Hi" }),
  ev(5, 30_000, "run", { snapshot_seq: 3, stdout: "ok", stderr: "", exit_code: 0, timed_out: false }),
  ev(6, 40_000, "code_snapshot", { code: "x = 2\n" }),
];

describe("replay at a moment", () => {
  it("shows the last snapshot at or before the time, else the starter code", () => {
    expect(codeAt(EVENTS, 19_999)).toBe("# start\n");
    expect(codeAt(EVENTS, 20_000)).toBe("x = 1\n");
    expect(codeAt(EVENTS, 99_000)).toBe("x = 2\n");
    expect(codeAt([], 5_000, "starter")).toBe("starter");
  });

  it("shows only the conversation so far", () => {
    expect(transcriptAt(EVENTS, 9_000)).toEqual([]);
    expect(transcriptAt(EVENTS, 25_000).map((l) => [l.speaker, l.text])).toEqual([
      ["interviewer", "Hello"],
      ["user", "Hi"],
    ]);
  });

  it("gives each Run the exact code that ran, even if the code changed after", () => {
    expect(runsAt(EVENTS, 29_000)).toEqual([]);
    const [run] = runsAt(EVENTS, 45_000);
    expect(run.code).toBe("x = 1\n");
    expect(run.stdout).toBe("ok");
    expect(run.exit_code).toBe(0);
  });

  it("formats positions as mm:ss", () => {
    expect(clock(65_000)).toBe("01:05");
    expect(clock(3_725_000)).toBe("62:05");
  });
});
