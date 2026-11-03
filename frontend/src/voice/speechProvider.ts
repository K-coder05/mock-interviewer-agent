// Speech-to-text behind one small interface, so the browser engine can be swapped (Whisper in
// v2) and the voice output layer (TTS, barge-in, echo guard) can sit on top of it.
//
// A provider reports interim results (the words so far, may still change) and final utterances
// with their start and end in the browser's clock (performance.now() ms). An utterance ends at a
// final result, or after `utteranceSilenceMs` with no new result: the interim text so far is then
// emitted as final.

export interface SpeechCallbacks {
  onInterim: (text: string) => void;
  onFinal: (text: string, startMs: number, endMs: number) => void;
  /** Recognition failed for good (no permission, no device): the Candidate can still type. */
  onError?: (message: string) => void;
}

export interface SpeechProvider {
  /** Start listening; keeps listening (restarting the engine as needed) until stop(). */
  start(): void;
  /** Stop listening; the interim utterance in progress is dropped. */
  stop(): void;
}

// The parts of the Web Speech API used here (not in TypeScript's DOM lib).
interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: RecognitionAlternative;
}
interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
}
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
}
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function webSpeechSupported(): boolean {
  return recognitionConstructor() !== null;
}

// Errors after which restarting can't help.
const FATAL_ERRORS = new Set(["not-allowed", "service-not-allowed", "audio-capture"]);
// Restarts back off while the engine keeps failing (e.g. no network), up to the max.
const RESTART_DELAY_MS = 250;
const MAX_RESTART_DELAY_MS = 10_000;

/** The browser's SpeechRecognition (Chrome/Edge), continuous with interim results. */
export class WebSpeechProvider implements SpeechProvider {
  private recognition: Recognition | null = null;
  private discarded: Recognition | null = null; // aborted after a silence boundary; ignored
  private active = false;
  private interim = "";
  private interimStartMs: number | null = null;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  private restartDelayMs = RESTART_DELAY_MS;
  private failed = false; // the current engine reported an error before ending

  constructor(
    private readonly callbacks: SpeechCallbacks,
    private readonly utteranceSilenceMs = 1200,
    private readonly lang = "en-US",
  ) {}

  start(): void {
    if (this.active) return;
    this.active = true;
    this.listen();
  }

  stop(): void {
    this.active = false;
    this.clearTimers();
    this.resetInterim();
    const recognition = this.recognition;
    this.recognition = null;
    this.discarded = null;
    recognition?.abort();
  }

  private listen(): void {
    const Constructor = recognitionConstructor();
    if (!Constructor) {
      this.active = false;
      this.callbacks.onError?.("Speech recognition needs Chrome or Edge.");
      return;
    }
    const recognition = new Constructor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = this.lang;
    recognition.onresult = (event) => {
      if (this.recognition !== recognition) return;
      this.restartDelayMs = RESTART_DELAY_MS; // it works: restart quickly next time
      this.onResult(event);
    };
    recognition.onerror = (event) => {
      if (this.recognition !== recognition) return;
      if (event.error !== "no-speech" && event.error !== "aborted") this.failed = true;
      if (!FATAL_ERRORS.has(event.error)) return;
      this.stop();
      this.callbacks.onError?.(`Speech recognition stopped: ${event.error}`);
    };
    // The engine ends after long silences (and after abort()): restart while still listening.
    recognition.onend = () => {
      if (recognition === this.discarded) this.discarded = null;
      else if (recognition === this.recognition) this.recognition = null;
      else return;
      if (!this.active) return;
      const delay = this.restartDelayMs;
      if (this.failed) this.restartDelayMs = Math.min(delay * 2, MAX_RESTART_DELAY_MS);
      this.restartTimer = setTimeout(() => {
        this.restartTimer = null;
        if (this.active) this.listen();
      }, delay);
    };
    this.failed = false;
    this.recognition = recognition;
    try {
      recognition.start();
    } catch (err) {
      this.stop();
      this.callbacks.onError?.(err instanceof Error ? err.message : String(err));
    }
  }

  private onResult(event: RecognitionEvent): void {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      const text = result[0]?.transcript ?? "";
      if (result.isFinal) {
        this.emitFinal(text);
      } else {
        interim += text;
      }
    }
    if (!interim.trim()) return;
    this.interim = interim;
    this.interimStartMs ??= performance.now();
    this.callbacks.onInterim(interim.trim());
    if (this.silenceTimer !== null) clearTimeout(this.silenceTimer);
    this.silenceTimer = setTimeout(() => this.endBySilence(), this.utteranceSilenceMs);
  }

  private emitFinal(text: string): void {
    const startMs = this.interimStartMs ?? performance.now();
    this.resetInterim();
    if (text.trim()) this.callbacks.onFinal(text.trim(), startMs, performance.now());
  }

  // No new result for a while: the interim text is the utterance. The engine would still
  // finalize it later, so discard that engine (its late results are ignored); its onend starts a
  // fresh one.
  private endBySilence(): void {
    this.silenceTimer = null;
    const text = this.interim;
    if (!text.trim()) return;
    const startMs = this.interimStartMs ?? performance.now();
    this.resetInterim();
    this.discarded = this.recognition;
    this.recognition = null;
    this.discarded?.abort();
    this.callbacks.onFinal(text.trim(), startMs, performance.now() - this.utteranceSilenceMs);
  }

  private resetInterim(): void {
    this.interim = "";
    this.interimStartMs = null;
    if (this.silenceTimer !== null) clearTimeout(this.silenceTimer);
    this.silenceTimer = null;
  }

  private clearTimers(): void {
    if (this.silenceTimer !== null) clearTimeout(this.silenceTimer);
    if (this.restartTimer !== null) clearTimeout(this.restartTimer);
    this.silenceTimer = null;
    this.restartTimer = null;
  }
}
