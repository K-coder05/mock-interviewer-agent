// The Interviewer's voice: a sentence-level text-to-speech queue on the browser's
// speechSynthesis. Replies stream in as text deltas; each complete sentence is spoken as soon as
// it arrives, so speech starts long before the reply has finished streaming.
//
// It also keeps what the echo guard needs: the text the Interviewer is speaking, and for a short
// tail after it stops (speech recognition reports words up to ~1.2 s late).

/** How long after the Interviewer stops speaking its text still counts as possible echo. */
export const ECHO_TAIL_MS = 3000;

export interface TtsOptions {
  /** A speechSynthesis voice name (or voiceURI); null or unknown = the browser default. */
  voiceName?: string | null;
  rate?: number;
  /** Speaking started (first sentence of a reply) or ended (the reply is done and spoken). */
  onSpeakingChange?: (speaking: boolean) => void;
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

// A sentence ends at . ! ? or … (plus closing quotes/brackets) followed by whitespace, or at a
// line break. Returns the complete sentences and the unfinished rest.
const SENTENCE_END = /[^.!?…\n]*(?:[.!?…]+["')\]]*\s+|\n+)/gy;

function takeSentences(buffer: string): { sentences: string[]; rest: string } {
  const sentences: string[] = [];
  SENTENCE_END.lastIndex = 0;
  let end = 0;
  for (let match = SENTENCE_END.exec(buffer); match; match = SENTENCE_END.exec(buffer)) {
    if (match[0].length === 0) break;
    if (match[0].trim()) sentences.push(match[0].trim());
    end = SENTENCE_END.lastIndex;
  }
  return { sentences, rest: buffer.slice(end) };
}

interface Reply {
  msgId: string;
  text: string; // everything received so far (the echo guard's reference)
  unspoken: string; // received text not yet queued as a sentence
  finished: boolean; // interviewer_done arrived
  endedAt: number | null; // when its speech ended (or was stopped)
}

export class SentenceTts {
  private enabled = true;
  private reply: Reply | null = null; // the reply being spoken
  private previous: Reply | null = null; // the one before, while still within the echo tail
  private queue: string[] = []; // sentences of `reply` waiting to be spoken
  private current: SpeechSynthesisUtterance | null = null;
  private dropped = new Set<string>(); // stopped replies: their later deltas are not spoken
  private speakingNow = false;

  constructor(private readonly options: TtsOptions = {}) {}

  /** True from a reply's first sentence until it is finished and fully spoken (or stopped). */
  get speaking(): boolean {
    return this.speakingNow;
  }

  /** Mute (false) or unmute the Interviewer's voice; muting stops any speech now. */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    if (!enabled) this.stop();
  }

  /** A streamed text delta of reply `msgId`. */
  push(msgId: string, text: string): void {
    const reply = this.replyFor(msgId);
    if (!reply) return;
    reply.text += text;
    reply.unspoken += text;
    const { sentences, rest } = takeSentences(reply.unspoken);
    reply.unspoken = rest;
    this.enqueue(sentences);
  }

  /** The reply is complete: speak what's left of it. */
  finish(msgId: string, fullText: string): void {
    const reply = this.replyFor(msgId);
    if (!reply) return;
    if (!reply.text) reply.text = reply.unspoken = fullText; // no deltas seen (e.g. joined late)
    reply.finished = true;
    const last = reply.unspoken.trim();
    reply.unspoken = "";
    this.enqueue(last ? [last] : []);
    this.update();
  }

  /** The server withdrew reply `msgId` (interviewer_cancel): stop speaking it. */
  cancel(msgId: string): void {
    this.dropped.add(msgId);
    if (this.reply?.msgId === msgId) this.stop();
  }

  /** Barge-in: stop speaking at once. Returns the reply that was cut off, if one was. */
  interrupt(): string | null {
    const msgId = this.speakingNow ? (this.reply?.msgId ?? null) : null;
    this.stop();
    return msgId;
  }

  /** The text the Interviewer is speaking, or spoke within the last ECHO_TAIL_MS. */
  echoReference(now = performance.now()): string {
    return [this.previous, this.reply]
      .filter((r): r is Reply => r !== null)
      .filter((r) => r.endedAt === null || now - r.endedAt < ECHO_TAIL_MS)
      .map((r) => r.text)
      .join(" ");
  }

  dispose(): void {
    this.enabled = false;
    this.stop();
  }

  private replyFor(msgId: string): Reply | null {
    if (!this.enabled || !ttsSupported() || this.dropped.has(msgId)) return null;
    if (this.reply?.msgId !== msgId) {
      if (this.reply) this.end(this.reply); // a new reply replaces an unfinished one
      this.previous = this.reply;
      this.queue = [];
      this.reply = { msgId, text: "", unspoken: "", finished: false, endedAt: null };
    }
    return this.reply;
  }

  private enqueue(sentences: string[]): void {
    this.queue.push(...sentences);
    this.speakNext();
  }

  private speakNext(): void {
    if (this.current || this.queue.length === 0) return this.update();
    const text = this.queue.shift() as string;
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = this.voice();
    if (voice) utterance.voice = voice;
    utterance.rate = this.options.rate ?? 1;
    const done = () => {
      if (this.current !== utterance) return; // stopped meanwhile
      this.current = null;
      this.speakNext();
    };
    utterance.onend = done;
    utterance.onerror = done;
    this.current = utterance;
    this.update();
    window.speechSynthesis.speak(utterance);
  }

  private voice(): SpeechSynthesisVoice | null {
    const name = this.options.voiceName;
    if (!name) return null;
    const voices = window.speechSynthesis.getVoices();
    return voices.find((v) => v.name === name || v.voiceURI === name) ?? null;
  }

  private stop(): void {
    if (this.reply) {
      this.dropped.add(this.reply.msgId);
      this.end(this.reply);
    }
    this.queue = [];
    if (this.current) {
      this.current = null;
      if (ttsSupported()) window.speechSynthesis.cancel();
    }
    this.update();
  }

  private end(reply: Reply): void {
    reply.endedAt ??= performance.now();
  }

  // Speaking while a sentence is playing or queued, or the reply is still streaming after its
  // first sentence started (so the pause between streamed sentences isn't "quiet").
  private update(): void {
    const reply = this.reply;
    const started = reply !== null && reply.text !== reply.unspoken; // a sentence was queued
    const streaming = started && reply.endedAt === null && !reply.finished;
    const speaking = this.current !== null || this.queue.length > 0 || streaming;
    if (!speaking && reply?.finished) this.end(reply);
    if (speaking !== this.speakingNow) {
      this.speakingNow = speaking;
      this.options.onSpeakingChange?.(speaking);
    }
  }
}
