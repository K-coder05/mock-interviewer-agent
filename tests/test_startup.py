"""Backend startup: refuses to start with a clear message when the API key is missing."""

import os
import subprocess
import sys

from backend.config import ROOT


def run_check(api_key: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}  # an explicit value beats any .env file
    return subprocess.run(
        [sys.executable, "-m", "backend", "--check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_backend_fails_fast_when_api_key_is_missing() -> None:
    result = run_check(api_key="")

    assert result.returncode != 0
    assert "ANTHROPIC_API_KEY is not set" in result.stderr
    assert "Traceback" not in result.stderr


def test_backend_check_passes_with_an_api_key() -> None:
    result = run_check(api_key="sk-test-not-real")

    assert result.returncode == 0, result.stderr
