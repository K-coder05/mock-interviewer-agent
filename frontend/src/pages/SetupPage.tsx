import { FormEvent, useState } from "react";
import { createSession } from "../api";
import { navigate } from "../App";

export function SetupPage() {
  const [problem, setProblem] = useState("");
  const [starterCode, setStarterCode] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(event: FormEvent) {
    event.preventDefault();
    setStarting(true);
    setError(null);
    try {
      const { session_id } = await createSession({
        problem_md: problem,
        starter_code: starterCode.trim() ? starterCode : undefined,
      });
      navigate(`/sessions/${session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStarting(false);
    }
  }

  return (
    <main className="setup">
      <h1>Mock Interviewer</h1>
      <form onSubmit={start}>
        <label>
          Problem statement (Markdown)
          <textarea
            required
            rows={14}
            value={problem}
            onChange={(e) => setProblem(e.target.value)}
            placeholder={"# Two Sum\n\nGiven an array of integers..."}
          />
        </label>
        <label>
          Function signature or starter code (optional)
          <textarea
            className="code"
            rows={6}
            value={starterCode}
            onChange={(e) => setStarterCode(e.target.value)}
            placeholder="def two_sum(nums: list[int], target: int) -> list[int]:"
          />
        </label>
        <p className="hint">
          Headphones recommended. Python 3, standard library only.
        </p>
        {error && <p className="error">Could not start the Session: {error}</p>}
        <button type="submit" disabled={starting || !problem.trim()}>
          {starting ? "Starting…" : "Start"}
        </button>
      </form>
    </main>
  );
}
