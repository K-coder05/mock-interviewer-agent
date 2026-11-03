# 02: Run your code

**What to build:** I can execute exactly what's in my editor with the Run button or Cmd/Ctrl+Enter, optionally feeding stdin, and see stdout, stderr, exit code and runtime in a console under the editor. Nothing is injected into my code. Runaway code is killed without freezing the UI. Every Run is recorded against the exact code that ran.

**Blocked by:** 01 (Skeleton: start a Session and type code)

**Status:** ready-for-agent

- [ ] Run executes the buffer with the system Python interpreter (configurable), not the backend's environment; only the standard library is importable
- [ ] Startup confirms the Runner interpreter is Python 3.11+
- [ ] `while True: pass` is killed at the timeout (process group) and the UI stays responsive
- [ ] Output beyond the per-stream cap is truncated with a visible marker
- [ ] Optional stdin is passed through
- [ ] A Run forces a code snapshot first; the `run` event references that snapshot's `seq`
- [ ] Clicking Run during a Run cancels it and starts a new one; only one Run per Session at a time
- [ ] Runner seam tests cover timeout, output cap, stdin, isolation and cancel-and-restart
