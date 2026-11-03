// Replay state at a chosen moment, computed from the Session's event log.

import type { SessionEvent } from "./api";

export interface TranscriptLine {
  key: string;
  speaker: "user" | "interviewer";
  text: string;
  t_ms: number;
}

export interface ReplayRun {
  t_ms: number;
  /** The exact code that ran (the snapshot the Run event references). */
  code: string;
  stdin: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
}

/** `mm:ss` for a position on the timeline (minutes keep counting past an hour). */
export function clock(tMs: number): string {
  const seconds = Math.floor(Math.max(0, tMs) / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function upTo(events: SessionEvent[], tMs: number): SessionEvent[] {
  return events.filter((e) => e.t_ms <= tMs);
}

/** The code as it stood at `tMs`: the last snapshot at or before it, else the starter code. */
export function codeAt(events: SessionEvent[], tMs: number, starterCode = ""): string {
  const last = upTo(events, tMs)
    .filter((e) => e.type === "code_snapshot")
    .pop();
  return last ? String(last.payload.code) : starterCode;
}

/** The conversation up to `tMs`. */
export function transcriptAt(events: SessionEvent[], tMs: number): TranscriptLine[] {
  return upTo(events, tMs)
    .filter((e) => e.type === "utterance")
    .map((e) => ({
      key: e.id,
      speaker: e.payload.speaker === "interviewer" ? "interviewer" : "user",
      text: String(e.payload.text),
      t_ms: e.t_ms,
    }));
}

/** Every Run up to `tMs`, each with the code that ran. */
export function runsAt(events: SessionEvent[], tMs: number, starterCode = ""): ReplayRun[] {
  const snapshots = new Map(
    events.filter((e) => e.type === "code_snapshot").map((e) => [e.seq, String(e.payload.code)]),
  );
  return upTo(events, tMs)
    .filter((e) => e.type === "run")
    .map((e) => ({
      t_ms: e.t_ms,
      code: snapshots.get(Number(e.payload.snapshot_seq)) ?? starterCode,
      stdin: String(e.payload.stdin ?? ""),
      stdout: String(e.payload.stdout ?? ""),
      stderr: String(e.payload.stderr ?? ""),
      exit_code: typeof e.payload.exit_code === "number" ? e.payload.exit_code : null,
      timed_out: e.payload.timed_out === true,
    }));
}
