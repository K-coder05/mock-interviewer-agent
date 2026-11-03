// Typed WebSocket client for one live Session. Reconnect/replay arrives with a later ticket.

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

export type ServerMessage =
  | { type: "timer"; state: TimerState; remaining_ms: number; duration_ms: number }
  | { type: "phase"; phase: Phase; by: "agent" | "user" }
  | { type: "session_ended"; reason: "user" | "timeout" }
  | { type: "error"; code: string; message: string }
  | { type: "interviewer_delta"; msg_id: string; text: string }
  | { type: "interviewer_done"; msg_id: string; full_text: string }
  | { type: "interviewer_cancel"; msg_id: string }
  | ({ type: "clarification"; seq: number } & Clarification)
  | { type: "run_started"; snapshot_seq: number }
  | ({ type: "run_result" } & RunResult);

export class SessionSocket {
  private socket: WebSocket;
  private queue: ClientMessage[] = [];

  constructor(sessionId: string, onMessage: (message: ServerMessage) => void) {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    this.socket = new WebSocket(
      `${scheme}://${window.location.host}/ws/sessions/${encodeURIComponent(sessionId)}`,
    );
    this.socket.addEventListener("open", () => {
      for (const message of this.queue.splice(0)) this.socket.send(JSON.stringify(message));
    });
    this.socket.addEventListener("message", (event) => {
      onMessage(JSON.parse(event.data as string) as ServerMessage);
    });
  }

  send(message: ClientMessage): void {
    if (this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else if (this.socket.readyState === WebSocket.CONNECTING) {
      this.queue.push(message);
    }
  }

  close(): void {
    this.socket.close();
  }
}
