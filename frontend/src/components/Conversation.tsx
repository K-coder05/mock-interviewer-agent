import { FormEvent, useEffect, useRef, useState } from "react";

export interface TranscriptEntry {
  key: string;
  speaker: "user" | "interviewer";
  text: string;
  streaming?: boolean;
}

interface Props {
  entries: TranscriptEntry[];
  onSend: (text: string) => void;
}

export function Conversation({ entries, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [entries]);

  function send(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    onSend(text);
    setDraft("");
  }

  return (
    <div className="conversation-box">
      <div className="transcript">
        {entries.length === 0 && <p className="hint">The Interviewer will greet you shortly.</p>}
        {entries.map((entry) => (
          <p key={entry.key} className={`turn ${entry.speaker}${entry.streaming ? " streaming" : ""}`}>
            <span className="speaker">{entry.speaker === "interviewer" ? "Interviewer" : "You"}</span>
            {entry.text}
          </p>
        ))}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={send}>
        <textarea
          rows={2}
          value={draft}
          placeholder="Type to the Interviewer (Enter to send)"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) send(e);
          }}
        />
        <button type="submit" disabled={!draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
