import { useEffect, useRef, useState } from "react";
import { getReplay, ReplayData } from "../api";
import { clock, codeAt, runsAt, transcriptAt } from "../replay";

interface Props {
  sessionId: string;
  /** The moment shown, in ms since the Session started. */
  t: number;
  onSeek: (tMs: number) => void;
}

/** A timeline scrubber with the read-only code at the chosen moment beside the transcript. */
export function ReplayPanel({ sessionId, t, onSeek }: Props) {
  const [data, setData] = useState<ReplayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    getReplay(sessionId)
      .then((d) => current && setData(d))
      .catch((err) => current && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      current = false;
    };
  }, [sessionId]);

  const lines = data ? transcriptAt(data.events, t) : [];
  useEffect(() => {
    // Scroll the transcript box itself, not the page.
    const box = transcriptRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [lines.length, data]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading replay…</p>;

  const total = Math.max(data.duration_ms, 1);
  const at = Math.min(Math.max(t, 0), total);
  const starter = data.session.starter_code ?? "";
  const runs = runsAt(data.events, at, starter);
  const lastRun = runs[runs.length - 1];

  return (
    <section className="replay" id="replay">
      <h2>Replay</h2>
      <div className="scrubber">
        <input
          type="range"
          min={0}
          max={total}
          step={1}
          value={at}
          aria-label="Replay position"
          onChange={(e) => onSeek(Number(e.target.value))}
        />
        <div className="markers">
          {data.markers.map((m, i) => (
            <button
              key={i}
              type="button"
              className={`marker marker-${m.kind}`}
              style={{
                left: `${Math.min(m.t_ms / total, 1) * 100}%`,
                width: m.end_ms ? `${((m.end_ms - m.t_ms) / total) * 100}%` : undefined,
              }}
              title={`${clock(m.t_ms)} ${m.label}`}
              onClick={() => onSeek(m.t_ms)}
            >
              <span className="sr-only">{m.label}</span>
            </button>
          ))}
        </div>
        <div className="marker-legend hint">
          <span className="marker-run">Run</span> <span className="marker-hint">Hint</span>{" "}
          <span className="marker-phase">Phase change</span>{" "}
          <span className="marker-silence">Silence</span>
        </div>
        <strong className="stamp">
          {clock(at)} / {clock(total)}
        </strong>
      </div>
      <div className="replay-body">
        <div className="replay-code">
          <h3>Code at {clock(at)}</h3>
          <pre className="code-view">{codeAt(data.events, at, starter)}</pre>
        </div>
        <div className="replay-transcript" ref={transcriptRef}>
          <h3>Transcript</h3>
          {lines.length === 0 && <p className="hint">Nothing said yet.</p>}
          {lines.map((line) => (
            <p
              key={line.key}
              className={`turn ${line.speaker}`}
            >
              <span className="speaker">
                {line.speaker === "interviewer" ? "Interviewer" : "You"} · {clock(line.t_ms)}
              </span>
              {line.text}
            </p>
          ))}
        </div>
      </div>
      {runs.length > 0 && (
        <div className="replay-runs">
          <h3>Runs so far</h3>
          <ol>
            {runs.map((run, i) => (
              <li key={i}>
                <details open={run === lastRun}>
                  <summary>
                    Run at {clock(run.t_ms)} ·{" "}
                    {run.exit_code === 0 && !run.timed_out ? "passed" : "failed"}
                  </summary>
                  <p className="hint">The code that ran</p>
                  <pre className="code-view">{run.code}</pre>
                  {run.stdin && <pre className="code-view">stdin: {run.stdin}</pre>}
                  <pre className="code-view run-output">
                    {run.stdout}
                    {run.stderr && <span className="stderr">{run.stderr}</span>}
                    {!run.stdout && !run.stderr && "(no output)"}
                  </pre>
                </details>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
