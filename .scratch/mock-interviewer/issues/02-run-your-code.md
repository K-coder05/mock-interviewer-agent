# 02: Run your code

**What to build:** I can execute exactly what's in my editor with the Run button or Cmd/Ctrl+Enter, optionally feeding stdin, and see stdout, stderr, exit code and runtime in a console under the editor. Nothing is injected into my code. Runaway code is killed without freezing the UI. Every Run is recorded against the exact code that ran.

**Blocked by:** 01 (Skeleton: start a Session and type code)

**Status:** done

- [x] Run executes the buffer with the system Python interpreter (configurable), not the backend's environment; only the standard library is importable
- [x] Startup confirms the Runner interpreter is Python 3.11+
- [x] `while True: pass` is killed at the timeout (process group) and the UI stays responsive
- [x] Output beyond the per-stream cap is truncated with a visible marker
- [x] Optional stdin is passed through
- [x] A Run forces a code snapshot first; the `run` event references that snapshot's `seq`
- [x] Clicking Run during a Run cancels it and starts a new one; only one Run per Session at a time
- [x] Runner seam tests cover timeout, output cap, stdin, isolation and cancel-and-restart

## Comments

**Built (ticket 02):**
- `backend/runner.py`: `Runner.run(code, stdin)` writes `main.py` to a fresh temp dir and runs `<python> -I -u -X utf8 main.py` with an empty env in its own process group (`start_new_session`); wall-clock timeout kills the group; per-stream cap with an `[output truncated at N KB]` marker (excess is drained, not buffered); `RLIMIT_AS` on Linux only. Cancelling the awaiting task kills the group. `resolve_interpreter` skips PATH entries inside the backend's venv (so `uv run` doesn't leak backend packages). `check_interpreter` is the startup check (3.11+), called from `python -m backend` (including `--check`).
- Config: `RunnerConfig` (`runner:` section of config.yaml) on `Config.runner`.
- Session engine: `run` message (`code`, `stdin?`) forces a snapshot (deduped; reuses the latest snapshot's seq), emits `run_started`, executes in a background task, then appends the `run` event (`snapshot_seq, stdin, stdout, stderr, exit_code, duration_ms, timed_out, truncated`) and emits `run_result`. A new `run` cancels the in-flight one; cancelled Runs leave no event. `SessionManager`/`LiveSession` now take a `runner`.
- Frontend: Console under the editor (Run button, Cmd/Ctrl+Enter via Monaco command, stdin box, stdout/stderr, exit code, runtime, "Timed out").
- Harness: `harness.finish_run(sid)` awaits the background Run; the harness builds a real `Runner`.

**Notes for later tickets:**
- Runs execute in the background, so `handle("run")` returns before the result; tests must `await harness.finish_run(sid)`. Ticket 10 (run reactions) should hook after the `run` event append in `LiveSession._execute`.
- A snapshot is now always recorded for the first `code_update`/`run` even if the buffer is empty and no starter existed.
- Not clicked through in a real browser; verified by tests only.
