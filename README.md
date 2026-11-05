# mock-interviewer-agent

A local mock coding interviewer: paste a problem, solve it in Python 3 in a browser editor, and
talk to a Claude-powered Interviewer. See `.scratch/mock-interviewer/spec.md` and `GLOSSARY.md`.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node 20+
- Chrome or Edge

## Install and run

```bash
cp .env.example .env    # set ANTHROPIC_API_KEY=...
make install            # uv sync (backend) + npm install (frontend)
make dev                # backend on :8000 + Vite on :5173 (proxies /api and /ws)
# open http://localhost:5173
```

The backend refuses to start, with a clear message, if `ANTHROPIC_API_KEY` is missing.
Tunables live in `config.yaml`; the SQLite database is `data/interviews.db` (gitignored).

API usage: every model call's tokens are stored (prep and Interviewer calls as private
`model_usage` events, the Report on its row); `GET /api/sessions/{id}/usage` sums them per
purpose with an estimated cost (prices in `backend/usage.py`). Re-running a problem with the same
statement, starter code and private notes reuses its earlier Problem Brief (no prep call).

## Development

```bash
make test        # pytest (no real API calls; the model is always a scripted fake) + vitest (echo guard)
make typecheck   # mypy --strict (backend + tests) and tsc (frontend)
make check       # both
uv run pytest tests/test_live_session.py   # a single test file
cd frontend && npm test                    # the frontend tests (echo-guard matcher)
RUN_PROMPT_REGRESSION=1 uv run pytest tests/test_prompt_regression.py   # opt-in, real API calls (see below)
make backend     # run only the backend (auto-reload)
make frontend    # run only the frontend
```

### Prompt-regression suite (opt-in, real API)

`tests/test_prompt_regression.py` runs scripted Sessions against the real Anthropic API (the real
Interviewer prompt, tools and model; only problem prep is scripted) in which the Candidate presses
the Interviewer: direct solution requests ("just tell me the answer"), test-input requests ("what
should I test?") and repeated pressure (a run of hint requests, then begging). Every Interviewer
utterance and logged Hint must contain no code block and no concrete test input, and Hint levels
must never exceed L4. It costs real money and the model is not deterministic, so it is skipped
unless both `RUN_PROMPT_REGRESSION=1` and `ANTHROPIC_API_KEY` are set; `make check` never runs it.
A failure names what leaked and the offending text; rerun once before blaming the prompt. The
detectors are pure functions in `tests/prompt_rules.py`, unit-tested in `tests/test_prompt_rules.py`
(default run).

Layout: `backend/` (FastAPI app, Session engine, SQLite store; `backend/agent/` holds the
Interviewer, its prompts and the trigger engine + guardrails in `triggers.py`), `frontend/` (React + Vite +
Monaco; `frontend/src/voice/` holds the speech-provider interface and its Web Speech implementation, the sentence TTS queue and the echo guard), `tests/` (pytest; `tests/harness.py` is the Live Session harness: message driver, `reconnect`/`restart` for reconnect replay and backend restarts,
fake clock, scripted fake model; `tests/report_harness.py` is the Report seam harness: event-log
fixtures, a scripted `submit_report`, and the Report generator). The Report lives in
`backend/feedback/` (rubric and Overall Signal, prompt, validation, background generator).
