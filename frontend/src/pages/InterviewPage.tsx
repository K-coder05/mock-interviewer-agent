import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getSession, SessionEvent, SessionInfo } from "../api";
import { CodeSync } from "../codeSync";
import { CodeEditor } from "../components/CodeEditor";
import { Console } from "../components/Console";
import { Conversation, TranscriptEntry } from "../components/Conversation";
import { Timer, TimerSnapshot } from "../components/Timer";
import { Clarification, Phase, PHASE_LABELS, PHASES, RunResult, SessionSocket } from "../ws";
import { isEcho } from "../voice/echoGuard";
import { webSpeechSupported, WebSpeechProvider } from "../voice/speechProvider";
import { SentenceTts, ttsSupported } from "../voice/tts";

// The server counts the Candidate as speaking for 1.5 s after each `speaking` signal, so
// interim results refresh it at least this often.
const SPEAKING_REFRESH_MS = 500;

// Muting the Interviewer's voice is a per-browser preference, kept across Sessions.
const INTERVIEWER_MUTED_KEY = "interviewerMuted";

function storedInterviewerMuted(): boolean {
  try {
    return window.localStorage.getItem(INTERVIEWER_MUTED_KEY) === "true";
  } catch {
    return false;
  }
}

function storeInterviewerMuted(muted: boolean): void {
  try {
    window.localStorage.setItem(INTERVIEWER_MUTED_KEY, String(muted));
  } catch {
    // not remembered; still applies to this Session
  }
}

function transcriptFrom(events: SessionEvent[]): TranscriptEntry[] {
  return events
    .filter((e) => e.type === "utterance")
    .map((e) => ({
      key: e.id,
      speaker: e.payload.speaker === "interviewer" ? "interviewer" : "user",
      text: String(e.payload.text),
    }));
}

function phaseFrom(events: SessionEvent[]): Phase {
  let phase: Phase = "clarify";
  for (const e of events) {
    if (e.type === "phase_changed" && PHASES.includes(e.payload.to as Phase)) {
      phase = e.payload.to as Phase;
    }
  }
  return phase;
}

// A reload keeps the mic as the Session last logged it.
function mutedFrom(events: SessionEvent[]): boolean {
  const last = events.filter((e) => e.type === "mic_muted" || e.type === "mic_unmuted").pop();
  return last?.type === "mic_muted";
}

function clarificationsFrom(events: SessionEvent[]): Clarification[] {
  return events
    .filter((e) => e.type === "clarification")
    .map((e) => e.payload as unknown as Clarification);
}

export function InterviewPage({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [stdin, setStdin] = useState("");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [clarifications, setClarifications] = useState<Clarification[]>([]);
  const [timer, setTimer] = useState<TimerSnapshot | null>(null);
  const [ended, setEnded] = useState(false);
  const [phase, setPhase] = useState<Phase>("clarify");
  const [interim, setInterim] = useState("");
  const [muted, setMuted] = useState(false);
  const [interviewerMuted, setInterviewerMuted] = useState(storedInterviewerMuted);
  const [ttsSpeaking, setTtsSpeaking] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(
    webSpeechSupported() ? null : "Voice needs Chrome or Edge; type instead.",
  );
  const stdinRef = useRef("");
  stdinRef.current = stdin;
  const bufferRef = useRef("");
  const syncRef = useRef<CodeSync | null>(null);
  const socketRef = useRef<SessionSocket | null>(null);
  const ttsRef = useRef<SentenceTts | null>(null);
  const interviewerMutedRef = useRef(interviewerMuted);
  interviewerMutedRef.current = interviewerMuted;
  const voice = session?.settings.voice;
  const ttsAvailable = ttsSupported() && voice?.tts !== "off";
  const pauseSttDuringTts = voice?.pause_stt_during_tts ?? false;

  useEffect(() => {
    let cancelled = false;
    getSession(sessionId)
      .then(({ session, events }) => {
        if (cancelled) return;
        setTranscript(transcriptFrom(events));
        setClarifications(clarificationsFrom(events));
        setPhase(phaseFrom(events));
        setMuted(mutedFrom(events));
        setEnded(session.status !== "live");
        setSession(session);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!session) return;
    bufferRef.current = session.starter_code ?? "";
    const settings = session.settings.voice;
    const tts =
      ttsSupported() && settings?.tts !== "off"
        ? new SentenceTts({
            voiceName: settings?.tts_voice,
            rate: settings?.tts_rate,
            onSpeakingChange: setTtsSpeaking,
          })
        : null;
    tts?.setEnabled(!interviewerMutedRef.current);
    ttsRef.current = tts;
    const socket = new SessionSocket(session.id, (message) => {
      if (message.type === "error") {
        setError(message.message);
        setRunning(false);
      } else if (message.type === "run_started") {
        setRunning(true);
        setResult(null);
      } else if (message.type === "run_result") {
        setRunning(false);
        setResult(message);
      } else if (message.type === "interviewer_delta") {
        tts?.push(message.msg_id, message.text);
        setTranscript((entries) => {
          const last = entries[entries.length - 1];
          if (last?.key === message.msg_id) {
            return [...entries.slice(0, -1), { ...last, text: last.text + message.text }];
          }
          const entry: TranscriptEntry = {
            key: message.msg_id,
            speaker: "interviewer",
            text: message.text,
            streaming: true,
          };
          return [...entries, entry];
        });
      } else if (message.type === "interviewer_done") {
        tts?.finish(message.msg_id, message.full_text);
        setTranscript((entries) => {
          const done: TranscriptEntry = {
            key: message.msg_id,
            speaker: "interviewer",
            text: message.full_text,
          };
          const index = entries.findIndex((e) => e.key === message.msg_id);
          return index < 0
            ? [...entries, done]
            : [...entries.slice(0, index), done, ...entries.slice(index + 1)];
        });
      } else if (message.type === "interviewer_cancel") {
        tts?.cancel(message.msg_id);
        setTranscript((entries) => entries.filter((e) => e.key !== message.msg_id));
      } else if (message.type === "timer") {
        setTimer({
          state: message.state,
          remainingMs: message.remaining_ms,
          receivedAt: performance.now(),
        });
      } else if (message.type === "phase") {
        setPhase(message.phase);
      } else if (message.type === "session_ended") {
        setEnded(true); // Report generation has started; the top bar links to it
      } else if (message.type === "clarification") {
        const { question, answer, by } = message;
        setClarifications((list) => [...list, { question, answer, by }]);
      }
    });
    socketRef.current = socket;
    const sync = new CodeSync(
      (code) => socket.send({ type: "code_update", code }),
      session.starter_code ?? "",
    );
    syncRef.current = sync;
    const flushOnLeave = () => sync.flush();
    window.addEventListener("beforeunload", flushOnLeave);
    return () => {
      window.removeEventListener("beforeunload", flushOnLeave);
      sync.flush();
      sync.dispose();
      socket.close();
      tts?.dispose();
      setTtsSpeaking(false);
      ttsRef.current = null;
      syncRef.current = null;
      socketRef.current = null;
    };
  }, [session]);

  // Always listening while the Session is live and the mic is not muted. Every final utterance
  // goes on the record; the Interviewer decides whether to respond. Listening goes on while the
  // Interviewer speaks: the echo guard drops its own voice, and anything else the Candidate says
  // stops it (barge-in). The speaker-only fallback stops listening while it speaks instead.
  const listenPaused = pauseSttDuringTts && ttsSpeaking;
  useEffect(() => {
    if (!session || ended || muted || voiceError || listenPaused) return;
    let lastSpeakingSent = 0;
    const send = (message: Parameters<SessionSocket["send"]>[0]) => socketRef.current?.send(message);
    const echo = (text: string) => isEcho(text, ttsRef.current?.echoReference() ?? "");
    const bargeIn = () => {
      const msgId = ttsRef.current?.interrupt();
      if (msgId) send({ type: "ui_event", event: "interrupted", msg_id: msgId });
    };
    const provider = new WebSpeechProvider(
      {
        onInterim: (text) => {
          if (echo(text)) return; // the Interviewer hearing itself
          bargeIn();
          setInterim(text);
          const now = performance.now();
          if (now - lastSpeakingSent >= SPEAKING_REFRESH_MS) {
            lastSpeakingSent = now;
            send({ type: "speaking", active: true });
          }
        },
        onFinal: (text, startMs, endMs) => {
          setInterim("");
          lastSpeakingSent = 0;
          send({ type: "speaking", active: false });
          if (echo(text)) return;
          bargeIn();
          syncRef.current?.flush(); // the reply must see the code as it is now
          send({ type: "utterance", text, channel: "voice", start_ms: startMs, end_ms: endMs });
          setTranscript((entries) => [
            ...entries,
            { key: `voice-${Date.now()}-${entries.length}`, speaker: "user", text },
          ]);
        },
        onError: setVoiceError,
      },
      session.settings.voice?.utterance_silence_ms,
    );
    provider.start();
    return () => {
      provider.stop();
      setInterim("");
      send({ type: "speaking", active: false });
    };
  }, [session, ended, muted, voiceError, listenPaused]);

  const toggleInterviewerMuted = () => {
    const next = !interviewerMuted;
    setInterviewerMuted(next);
    storeInterviewerMuted(next);
    ttsRef.current?.setEnabled(!next);
  };

  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    socketRef.current?.send({ type: "ui_event", event: "mute", muted: next });
  };

  // The run message carries the live buffer, which also becomes a forced snapshot server-side;
  // flushing first keeps any pending debounced update from arriving after it.
  const run = (code: string) => {
    syncRef.current?.flush();
    socketRef.current?.send({ type: "run", code, stdin: stdinRef.current });
  };

  // Flush the buffer first so the reply sees the code as it is now.
  const say = (text: string) => {
    syncRef.current?.flush();
    socketRef.current?.send({ type: "utterance", text, channel: "text" });
    setTranscript((entries) => [
      ...entries,
      { key: `local-${Date.now()}-${entries.length}`, speaker: "user", text },
    ]);
  };

  const choosePhase = (next: Phase) => {
    setPhase(next);
    socketRef.current?.send({ type: "set_phase", phase: next });
  };

  const endInterview = () => {
    if (!window.confirm("End the interview now?")) return;
    syncRef.current?.flush();
    socketRef.current?.send({ type: "end_session" });
  };

  if (!session) {
    return <main className="loading">{error ?? "Loading…"}</main>;
  }

  return (
    <div className="interview">
      <header className="topbar">
        <strong>{session.title}</strong>
        <nav className="phases" aria-label="Phase">
          {PHASES.map((p) => (
            <button
              key={p}
              type="button"
              className={p === phase ? "phase current" : "phase"}
              aria-current={p === phase ? "step" : undefined}
              disabled={ended}
              onClick={() => choosePhase(p)}
            >
              {PHASE_LABELS[p]}
            </button>
          ))}
        </nav>
        {error && <span className="error">{error}</span>}
        {voiceError ? (
          <span className="hint" title={voiceError}>
            Mic off
          </span>
        ) : (
          <button
            type="button"
            className={`mic-button ${muted ? "muted" : "listening"}`}
            aria-pressed={muted}
            disabled={ended}
            onClick={toggleMute}
            title={muted ? "Unmute your mic" : "Mute your mic"}
          >
            {muted ? "Mic muted" : "Mic on"}
          </button>
        )}
        {ttsAvailable && (
          <button
            type="button"
            className={`voice-button ${interviewerMuted ? "muted" : "speaking"}`}
            aria-pressed={interviewerMuted}
            onClick={toggleInterviewerMuted}
            title={
              interviewerMuted
                ? "Hear the Interviewer's replies"
                : "Mute the Interviewer: read replies as text only"
            }
          >
            {interviewerMuted ? "Interviewer muted" : "Interviewer voice on"}
          </button>
        )}
        <Timer timer={ended ? { state: "ended", remainingMs: 0, receivedAt: 0 } : timer} />
        {ended ? (
          <a className="report-link" href={`#/sessions/${session.id}/report`}>
            View report
          </a>
        ) : (
          <button type="button" className="end-button" onClick={endInterview}>
            End Interview
          </button>
        )}
      </header>
      <section className="pane problem">
        <ReactMarkdown>{session.problem_md}</ReactMarkdown>
        {clarifications.length > 0 && (
          <div className="clarifications">
            <h3>Clarifications</h3>
            <ul>
              {clarifications.map((c, i) => (
                <li key={i}>
                  <strong>{c.question}</strong> {c.answer}
                  {c.by === "candidate" && <span className="hint"> (your assumption)</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <section className="pane editor">
        <div className="editor-box">
          <CodeEditor
            initialCode={session.starter_code ?? ""}
            autocomplete={session.settings.autocomplete}
            onChange={(code) => {
              bufferRef.current = code;
              syncRef.current?.change(code);
            }}
            onRun={run}
            onPaste={(text) => socketRef.current?.send({ type: "ui_event", event: "paste", text })}
          />
        </div>
        <Console
          running={running}
          result={result}
          stdin={stdin}
          onStdinChange={setStdin}
          onRun={() => run(bufferRef.current)}
        />
      </section>
      <section className="pane conversation">
        <Conversation entries={transcript} interim={interim} onSend={say} disabled={ended} />
        {voiceError && !ended && <p className="hint">{voiceError}</p>}
        {ended && (
          <p className="ended-note">
            The interview has ended. <a href={`#/sessions/${session.id}/report`}>View report</a>
          </p>
        )}
      </section>
    </div>
  );
}
