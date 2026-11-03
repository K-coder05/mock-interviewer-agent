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
const RESTART_DELAY_MS = 250;

/** The browser's SpeechRecognition (Chrome/Edge), continuous with interim results. */
export class WebSpeechProvider implements SpeechProvider {
  private recognition: Recognition | null = null;
  private active = false;
  private interim = "";
  private interimStartMs: number | null = null;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;

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
      if (this.recognition === recognition) this.onResult(event);
    };
    recognition.onerror = (event) => {
      if (this.recognition !== recognition || !FATAL_ERRORS.has(event.error)) return;
      this.stop();
      this.callbacks.onError?.(`Speech recognition stopped: ${event.error}`);
    };
    // The engine ends after long silences (and after abort()): restart while still listening.
    recognition.onend = () => {
      if (this.recognition !== recognition || !this.active) return;
      this.recognition = null;
      this.restartTimer = setTimeout(() => {
        this.restartTimer = null;
        if (this.active) this.listen();
      }, RESTART_DELAY_MS);
    };
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
  // finalize it later, so drop its pending result by restarting it (abort, then onend restarts).
  private endBySilence(): void {
    this.silenceTimer = null;
    const text = this.interim;
    if (!text.trim()) return;
    const startMs = this.interimStartMs ?? performance.now();
    this.resetInterim();
    this.callbacks.onFinal(text.trim(), startMs, performance.now() - this.utteranceSilenceMs);
    this.recognition?.abort();
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
