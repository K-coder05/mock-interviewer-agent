import { RunResult } from "../ws";

interface Props {
  running: boolean;
  result: RunResult | null;
  stdin: string;
  onStdinChange: (stdin: string) => void;
  onRun: () => void;
}

export function Console({ running, result, stdin, onStdinChange, onRun }: Props) {
  return (
    <div className="console">
      <div className="console-bar">
        <button onClick={onRun}>{running ? "Restart run" : "Run"}</button>
        <span className="hint">Cmd/Ctrl+Enter</span>
        {running && <span className="hint">Running…</span>}
        {result && !running && (
          <span className={result.exit_code === 0 && !result.timed_out ? "ok" : "error"}>
            {result.timed_out ? "Timed out" : `Exit ${result.exit_code}`} · {result.duration_ms} ms
          </span>
        )}
      </div>
      <div className="console-body">
        <textarea
          className="stdin"
          placeholder="stdin (optional)"
          value={stdin}
          onChange={(e) => onStdinChange(e.target.value)}
        />
        <div className="output">
          {result?.stdout && <pre>{result.stdout}</pre>}
          {result?.stderr && <pre className="stderr">{result.stderr}</pre>}
          {result && !result.stdout && !result.stderr && <pre className="hint">(no output)</pre>}
        </div>
      </div>
    </div>
  );
}
