// Typed WebSocket client for one live Session. Reconnect/replay arrives with a later ticket.

export type ClientMessage =
  | { type: "code_update"; code: string }
  | { type: "run"; code: string; stdin: string };

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

export type ServerMessage =
  | { type: "error"; code: string; message: string }
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
