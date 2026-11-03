import { FormEvent, useState } from "react";
import { createSession, STYLE_PRESETS, StyleSetting } from "../api";
import { navigate } from "../App";

const CUSTOM = "custom";

export function SetupPage() {
  const [problem, setProblem] = useState("");
  const [starterCode, setStarterCode] = useState("");
  const [privateNotes, setPrivateNotes] = useState("");
  const [stylePick, setStylePick] = useState(STYLE_PRESETS[0].id);
  const [customStyle, setCustomStyle] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const style: StyleSetting =
    stylePick === CUSTOM ? { custom: customStyle.trim() } : { preset: stylePick };
  const ready = problem.trim() !== "" && (stylePick !== CUSTOM || customStyle.trim() !== "");

  async function start(event: FormEvent) {
    event.preventDefault();
    setStarting(true);
    setError(null);
    try {
      const { session_id } = await createSession({
        problem_md: problem,
        starter_code: starterCode.trim() ? starterCode : undefined,
        private_notes: privateNotes.trim() ? privateNotes : undefined,
        style,
      });
      navigate(`/sessions/${session_id}`);
    } catch (err) {
      // Back to the form with every input intact; no Session was created.
      setError(err instanceof Error ? err.message : String(err));
      setStarting(false);
    }
  }

  if (starting) {
    return (
      <main className="loading reading">
        <p>Interviewer is reading the problem…</p>
        <p className="hint">This can take up to a minute.</p>
      </main>
    );
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
        <label>
          Private notes for the Interviewer (optional, hidden from you during the Session)
          <textarea
            rows={3}
            value={privateNotes}
            onChange={(e) => setPrivateNotes(e.target.value)}
            placeholder="e.g. The intended solution is O(n) with a hash map."
          />
        </label>
        <label>
          Interviewer style
          <select value={stylePick} onChange={(e) => setStylePick(e.target.value)}>
            {STYLE_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
            <option value={CUSTOM}>Describe your own…</option>
          </select>
        </label>
        {stylePick === CUSTOM && (
          <label>
            Describe the interviewer
            <textarea
              rows={2}
              value={customStyle}
              onChange={(e) => setCustomStyle(e.target.value)}
              placeholder="e.g. A terse staff engineer who probes trade-offs hard."
            />
          </label>
        )}
        <p className="hint">
          Headphones recommended. Python 3, standard library only. Style changes only the
          Interviewer's persona, never how you're scored.
        </p>
        {error && <p className="error">Could not start the Session: {error}</p>}
        <button type="submit" disabled={!ready}>
          Start
        </button>
      </form>
    </main>
  );
}
