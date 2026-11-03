// Typed WebSocket client for one live Session. It reconnects on its own after a drop, sending
// the last event seq the page has seen so the server replays what it missed.

import type { SessionEvent } from "./api";

export type ClientMessage =
  | { type: "code_update"; code: string }
  | { type: "run"; code: string; stdin: string }
  | { type: "utterance"; text: string; channel: "text" }
  | { type: "utterance"; text: string; channel: "voice"; start_ms: number; end_ms: number }
  | { type: "speaking"; active: boolean }
  | { type: "ui_event"; event: "paste"; text: string }
  | { type: "ui_event"; event: "mute"; muted: boolean }
  | { type: "ui_event"; event: "interrupted"; msg_id: string }
  | { type: "set_phase"; phase: Phase }
  | { type: "end_session" };

export const PHASES = ["clarify", "approach", "implement", "test", "wrap_up"] as const;
export type Phase = (typeof PHASES)[number];
export const PHASE_LABELS: Record<Phase, string> = {
  clarify: "Clarify",
  approach: "Approach",
  implement: "Implement",
  test: "Test",
  wrap_up: "Wrap-up",
};

export interface RunResult {
  snapshot_seq: number;
  stdin: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
  timed_out: boolean;
  truncated: boolean;
}

export interface Clarification {
  question: string;
  answer: string;
  by: "interviewer" | "candidate";
}

export type TimerState = "running" | "warning" | "time_up" | "ended";

// Messages for a logged event carry its `seq`.
export type ServerMessage =
  | { type: "replay"; events: SessionEvent[]; last_seq: number | null }
  | { type: "timer"; state: TimerState; remaining_ms: number; duration_ms: number }
  | { type: "phase"; phase: Phase; by: "agent" | "user"; seq: number }
  | { type: "session_ended"; reason: "user" | "timeout"; seq: number }
  | { type: "error"; code: string; message: string }
  | { type: "interviewer_delta"; msg_id: string; text: string }
  | { type: "interviewer_done"; msg_id: string; full_text: string; seq: number }
  | { type: "interviewer_cancel"; msg_id: string }
  | ({ type: "clarification"; seq: number } & Clarification)
  | { type: "run_started"; snapshot_seq: number }
  | ({ type: "run_result"; seq: number } & RunResult);

export type ServerMessageHandler = (message: ServerMessage) => void;

export type ConnectionState = "open" | "reconnecting" | "closed";

const RETRY_MIN_MS = 500;
const RETRY_MAX_MS = 5_000;
const NOT_LIVE_CLOSE_CODE = 4404; // the server has no live Session by that id: don't retry

export class SessionSocket {
  private socket: WebSocket | null = null;
  private queue: ClientMessage[] = []; // sent once (re)connected
  private closed = false;
  private retryMs = RETRY_MIN_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly sessionId: string,
    private readonly lastSeq: () => number,
    private readonly onMessage: ServerMessageHandler,
    private readonly onState: (state: ConnectionState) => void = () => {},
  ) {
    this.connect();
  }

  send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else if (!this.closed && message.type !== "speaking") {
      // `speaking` is momentary; only the latest buffer matters for code
      if (message.type === "code_update") {
        this.queue = this.queue.filter((m) => m.type !== "code_update");
      }
      this.queue.push(message);
    }
  }

  /** Stop for good. Messages still waiting for the socket to open are sent first. */
  close(): void {
    this.closed = true;
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    const socket = this.socket;
    if (socket?.readyState === WebSocket.CONNECTING && this.queue.length > 0) {
      socket.addEventListener("open", () => socket.close());
    } else {
      socket?.close();
    }
  }

  private connect(): void {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const id = encodeURIComponent(this.sessionId);
    const socket = new WebSocket(
      `${scheme}://${window.location.host}/ws/sessions/${id}?last_seq=${this.lastSeq()}`,
    );
    this.socket = socket;
    socket.addEventListener("open", () => {
      this.retryMs = RETRY_MIN_MS;
      for (const message of this.queue.splice(0)) socket.send(JSON.stringify(message));
      if (!this.closed) this.onState("open");
    });
    socket.addEventListener("message", (event) => {
      if (!this.closed) this.onMessage(JSON.parse(event.data as string) as ServerMessage);
    });
    socket.addEventListener("close", (event) => {
      if (this.closed) return;
      if (event.code === NOT_LIVE_CLOSE_CODE) {
        this.closed = true;
        this.onState("closed");
        return;
      }
      this.onState("reconnecting");
      this.retryTimer = setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
    });
  }
}
