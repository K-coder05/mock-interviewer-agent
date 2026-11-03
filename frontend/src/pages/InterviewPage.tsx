import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getSession, SessionInfo } from "../api";
import { CodeSync } from "../codeSync";
import { CodeEditor } from "../components/CodeEditor";
import { SessionSocket } from "../ws";

export function InterviewPage({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const syncRef = useRef<CodeSync | null>(null);

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
    const socket = new SessionSocket(session.id, (message) => {
      if (message.type === "error") setError(message.message);
    });
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
    };
  }, [session]);

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
        <CodeEditor
          initialCode={session.starter_code ?? ""}
          autocomplete={session.settings.autocomplete}
          onChange={(code) => syncRef.current?.change(code)}
        />
      </section>
      <section className="pane conversation">
        <p className="hint">The Interviewer will appear here.</p>
      </section>
    </div>
  );
}
