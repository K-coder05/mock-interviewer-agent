"""Runner: executes the Candidate's buffer, exactly as written, in a throwaway subprocess.

The buffer is written to a fresh temp dir as `main.py` and run with the *system* Python in
isolated mode (`-I`: no user site-packages, no PYTHON* env vars), so only the standard library is
importable. Limits: wall-clock timeout (the whole process group is killed), per-stream output cap,
and an address-space limit where the OS enforces it (Linux; macOS largely ignores it).
This guards against accidental runaway code, not malicious code.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.config import ConfigError, RunnerConfig

MIN_PYTHON = (3, 11)
_PIPE_GRACE_S = 1.0


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool
    truncated: bool


def _own_prefixes() -> list[Path]:
    prefixes = {Path(sys.prefix).resolve()} if sys.prefix != sys.base_prefix else set()
    if venv := os.environ.get("VIRTUAL_ENV"):
        prefixes.add(Path(venv).resolve())
    return list(prefixes)


def resolve_interpreter(name: str) -> str:
    """Find the Runner interpreter. A bare name is looked up on PATH, skipping the backend's own
    virtualenv so the Candidate never sees the backend's packages."""
    if os.sep in name:
        return name
    prefixes = _own_prefixes()
    entries = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        resolved = Path(entry).resolve() if entry else None
        if resolved is not None and not any(p in (resolved, *resolved.parents) for p in prefixes):
            entries.append(entry)
    found = shutil.which(name, path=os.pathsep.join(entries))
    if found is None:
        raise ConfigError(f"Runner interpreter {name!r} not found on PATH (outside the backend venv)")
    return found


def check_interpreter(config: RunnerConfig) -> str:
    """Startup check: the Runner interpreter exists and is Python 3.11+. Returns its path."""
    path = resolve_interpreter(config.python)
    try:
        out = subprocess.run(
            [path, "-I", "-c", "import sys; print(*sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
            env={},
        )
        major, minor = (int(part) for part in out.stdout.split())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"Cannot run the Runner interpreter {path!r}: {exc}") from exc
    if (major, minor) < MIN_PYTHON:
        raise ConfigError(
            f"Runner interpreter {path} is Python {major}.{minor}; Python 3.11+ is required. "
            "Set runner.python in config.yaml."
        )
    return path


class _Capture:
    """Collects one output stream up to the cap, discarding the rest so the child never blocks."""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._buf = bytearray()
        self.cut = False

    async def read_from(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(65536):
            room = self._cap - len(self._buf)
            self._buf += chunk[: max(room, 0)]
            if len(chunk) > room:
                self.cut = True

    def text(self) -> str:
        text = self._buf.decode("utf-8", errors="replace")
        if self.cut:
            text += f"\n[output truncated at {self._cap // 1024} KB]\n"
        return text


class Runner:
    def __init__(self, config: RunnerConfig, *, python: str | None = None) -> None:
        self._python = python or resolve_interpreter(config.python)
        self._timeout_s = config.timeout_s
        self._memory_bytes = config.memory_mb * 1024 * 1024
        self._cap = config.output_cap_kb * 1024

    async def run(self, code: str, stdin: str = "") -> RunResult:
        """Execute `code`. Cancelling the awaiting task kills the process group."""
        with tempfile.TemporaryDirectory(prefix="interview-run-") as workdir:
            (Path(workdir) / "main.py").write_text(code, encoding="utf-8")
            started = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                self._python, "-I", "-u", "-X", "utf8", "main.py",
                cwd=workdir,
                env={},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # own process group, so grandchildren die too
                preexec_fn=self._limit_memory(),
            )
            assert proc.stdin and proc.stdout and proc.stderr
            out, err = _Capture(self._cap), _Capture(self._cap)
            readers = [
                asyncio.create_task(out.read_from(proc.stdout)),
                asyncio.create_task(err.read_from(proc.stderr)),
            ]
            timed_out = False
            try:
                async with asyncio.timeout(self._timeout_s):
                    await self._feed(proc.stdin, stdin.encode("utf-8"))
                    await proc.wait()
                    # Readers hit EOF once the pipes close; a lingering grandchild holding them
                    # open must not turn a finished program into a "timeout".
                    await asyncio.wait(readers, timeout=_PIPE_GRACE_S)
            except TimeoutError:
                timed_out = True
            finally:  # also runs on cancellation
                self._kill_group(proc)
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                await proc.wait()
            return RunResult(
                stdout=out.text(),
                stderr=err.text(),
                exit_code=proc.returncode if proc.returncode is not None else -1,
                duration_ms=round((time.monotonic() - started) * 1000),
                timed_out=timed_out,
                truncated=out.cut or err.cut,
            )

    @staticmethod
    async def _feed(stdin: asyncio.StreamWriter, data: bytes) -> None:
        try:
            stdin.write(data)
            await stdin.drain()
            stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the program exited without reading its stdin

    def _limit_memory(self) -> Callable[[], None] | None:
        if sys.platform != "linux":
            return None
        limit = self._memory_bytes

        def apply() -> None:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        return apply

    @staticmethod
    def _kill_group(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


__all__ = ["RunResult", "Runner", "check_interpreter", "resolve_interpreter"]
