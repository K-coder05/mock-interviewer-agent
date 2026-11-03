import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getSession, SessionInfo } from "../api";
import { CodeSync } from "../codeSync";
import { CodeEditor } from "../components/CodeEditor";
import { Console } from "../components/Console";
import { RunResult, SessionSocket } from "../ws";

export function InterviewPage({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [stdin, setStdin] = useState("");
  const stdinRef = useRef("");
  stdinRef.current = stdin;
  const bufferRef = useRef("");
  const syncRef = useRef<CodeSync | null>(null);
  const socketRef = useRef<SessionSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSession(sessionId)
      .then(({ session }) => !cancelled && setSession(session))
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

  if (!session) {
    return <main className="loading">{error ?? "Loading…"}</main>;
  }

  return (
    <div className="interview">
      <header className="topbar">
        <strong>{session.title}</strong>
        {error && <span className="error">{error}</span>}
      </header>
      <section className="pane problem">
        <ReactMarkdown>{session.problem_md}</ReactMarkdown>
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
        <p className="hint">The Interviewer will appear here.</p>
      </section>
    </div>
  );
}
