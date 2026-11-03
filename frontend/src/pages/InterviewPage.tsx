import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getSession, SessionEvent, SessionInfo } from "../api";
import { CodeSync } from "../codeSync";
import { CodeEditor } from "../components/CodeEditor";
import { Console } from "../components/Console";
import { Conversation, TranscriptEntry } from "../components/Conversation";
import { Timer, TimerSnapshot } from "../components/Timer";
import { Clarification, RunResult, SessionSocket } from "../ws";

function transcriptFrom(events: SessionEvent[]): TranscriptEntry[] {
  return events
    .filter((e) => e.type === "utterance")
    .map((e) => ({
      key: e.id,
      speaker: e.payload.speaker === "interviewer" ? "interviewer" : "user",
      text: String(e.payload.text),
    }));
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
  const stdinRef = useRef("");
  stdinRef.current = stdin;
  const bufferRef = useRef("");
  const syncRef = useRef<CodeSync | null>(null);
  const socketRef = useRef<SessionSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSession(sessionId)
      .then(({ session, events }) => {
        if (cancelled) return;
        setTranscript(transcriptFrom(events));
        setClarifications(clarificationsFrom(events));
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
        setTranscript((entries) => entries.filter((e) => e.key !== message.msg_id));
      } else if (message.type === "timer") {
        setTimer({
          state: message.state,
          remainingMs: message.remaining_ms,
          receivedAt: performance.now(),
        });
      } else if (message.type === "session_ended") {
        setEnded(true);
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
      syncRef.current = null;
      socketRef.current = null;
    };
  }, [session]);

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
        {error && <span className="error">{error}</span>}
        <Timer timer={ended ? { state: "ended", remainingMs: 0, receivedAt: 0 } : timer} />
        <button type="button" className="end-button" disabled={ended} onClick={endInterview}>
          End Interview
        </button>
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
        <Conversation entries={transcript} onSend={say} disabled={ended} />
        {ended && <p className="ended-note">The interview has ended.</p>}
      </section>
    </div>
  );
}
