// Decides when the editor buffer is sent to the backend: after `idleMs` without typing, or at
// most every `maxWaitMs` while typing continuously, whichever comes first. `flush()` sends
// immediately (later tickets call it before each final utterance and each Run). An unchanged
// buffer is never re-sent; the backend dedupes too.

export interface CodeSyncOptions {
  idleMs: number;
  maxWaitMs: number;
}

export const DEFAULT_CODE_SYNC: CodeSyncOptions = { idleMs: 1500, maxWaitMs: 10_000 };

export class CodeSync {
  private pending: string | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private maxWaitTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly send: (code: string) => void,
    private lastSent: string,
    private readonly options: CodeSyncOptions = DEFAULT_CODE_SYNC,
  ) {}

  change(code: string): void {
    this.pending = code;
    if (this.idleTimer !== null) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => this.flush(), this.options.idleMs);
    if (this.maxWaitTimer === null) {
      this.maxWaitTimer = setTimeout(() => this.flush(), this.options.maxWaitMs);
    }
  }

  flush(): void {
    this.clearTimers();
    const code = this.pending;
    this.pending = null;
    if (code !== null && code !== this.lastSent) {
      this.lastSent = code;
      this.send(code);
    }
  }

  dispose(): void {
    this.clearTimers();
  }

  private clearTimers(): void {
    if (this.idleTimer !== null) clearTimeout(this.idleTimer);
    if (this.maxWaitTimer !== null) clearTimeout(this.maxWaitTimer);
    this.idleTimer = null;
    this.maxWaitTimer = null;
  }
}
