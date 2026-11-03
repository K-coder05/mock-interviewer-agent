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

## Development

```bash
make test        # pytest (no real API calls; the model is always a scripted fake) + vitest (echo guard)
make typecheck   # mypy --strict (backend + tests) and tsc (frontend)
make check       # both
uv run pytest tests/test_live_session.py   # a single test file
cd frontend && npm test                    # the frontend tests (echo-guard matcher)
make backend     # run only the backend (auto-reload)
make frontend    # run only the frontend
```

Layout: `backend/` (FastAPI app, Session engine, SQLite store; `backend/agent/` holds the
Interviewer, its prompts and the trigger engine + guardrails in `triggers.py`), `frontend/` (React + Vite +
Monaco; `frontend/src/voice/` holds the speech-provider interface and its Web Speech implementation, the sentence TTS queue and the echo guard), `tests/` (pytest; `tests/harness.py` is the Live Session harness: message driver,
fake clock, scripted fake model; `tests/report_harness.py` is the Report seam harness: event-log
fixtures, a scripted `submit_report`, and the Report generator). The Report lives in
`backend/feedback/` (rubric and Overall Signal, prompt, validation, background generator).
