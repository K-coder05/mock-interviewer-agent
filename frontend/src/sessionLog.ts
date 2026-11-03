// Interview page state rebuilt from the Session's event log: on load (all events) and after a
// reconnect (the `replay` of the events the page missed).

import type { SessionEvent } from "./api";
import type { TranscriptEntry } from "./components/Conversation";
import { Clarification, Phase, PHASES, RunResult } from "./ws";

// Entries the page added itself when the Candidate typed or spoke, not yet matched to a logged
// utterance.
const LOCAL_PREFIXES = ["local-", "voice-"];

function isLocal(entry: TranscriptEntry): boolean {
  return LOCAL_PREFIXES.some((prefix) => entry.key.startsWith(prefix));
}

/** Add logged utterances to the transcript without duplicating what it already shows: an
 * Interviewer reply replaces its streamed entry (same msg_id); the Candidate's own words match
 * the entry the page added when they were sent. */
export function mergeUtterances(
  entries: TranscriptEntry[],
  events: SessionEvent[],
): TranscriptEntry[] {
  let merged = entries;
  for (const e of events) {
    if (e.type !== "utterance") continue;
    const text = String(e.payload.text);
    if (e.payload.speaker === "interviewer") {
      const key = typeof e.payload.msg_id === "string" ? e.payload.msg_id : e.id;
      const entry: TranscriptEntry = { key, speaker: "interviewer", text };
      const index = merged.findIndex((x) => x.key === key);
      merged =
        index < 0
          ? [...merged, entry]
          : [...merged.slice(0, index), entry, ...merged.slice(index + 1)];
    } else {
      const entry: TranscriptEntry = { key: e.id, speaker: "user", text };
      const index = merged.findIndex(
        (x) => isLocal(x) && x.speaker === "user" && x.text.trim() === text.trim(),
      );
      merged =
        index < 0
          ? [...merged, entry]
          : [...merged.slice(0, index), entry, ...merged.slice(index + 1)];
    }
  }
  return merged;
}

export function phaseFrom(events: SessionEvent[], phase: Phase = "clarify"): Phase {
  for (const e of events) {
    if (e.type === "phase_changed" && PHASES.includes(e.payload.to as Phase)) {
      phase = e.payload.to as Phase;
    }
  }
  return phase;
}

/** The mic as the Session last logged it, if the events say. */
export function mutedFrom(events: SessionEvent[]): boolean | undefined {
  const last = events.filter((e) => e.type === "mic_muted" || e.type === "mic_unmuted").pop();
  return last && last.type === "mic_muted";
}

export function clarificationsFrom(events: SessionEvent[]): Clarification[] {
  return events
    .filter((e) => e.type === "clarification")
    .map((e) => e.payload as unknown as Clarification);
}

/** The code as last recorded, if any snapshot was. */
export function codeFrom(events: SessionEvent[]): string | undefined {
  const last = events.filter((e) => e.type === "code_snapshot").pop();
  return last && String(last.payload.code);
}

export function lastRunFrom(events: SessionEvent[]): RunResult | undefined {
  const last = events.filter((e) => e.type === "run").pop();
  return last && (last.payload as unknown as RunResult);
}

export function lastSeqOf(events: SessionEvent[], seq = 0): number {
  return events.reduce((max, e) => Math.max(max, e.seq), seq);
}
