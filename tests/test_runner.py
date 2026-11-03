"""Runner seam: real subprocesses, no mocks."""

import asyncio
import os
import stat
import time
from pathlib import Path

import pytest

from backend.config import ConfigError, RunnerConfig
from backend.runner import Runner, check_interpreter


def make_runner(**overrides: float) -> Runner:
    return Runner(RunnerConfig(**{"timeout_s": 5, **overrides}))  # type: ignore[arg-type]


async def test_runs_the_buffer_and_reports_stdout_stderr_exit_code_and_duration() -> None:
    result = await make_runner().run("import sys\nprint('hi')\nprint('oops', file=sys.stderr)\nsys.exit(3)\n")

    assert result.stdout == "hi\n"
    assert result.stderr == "oops\n"
    assert result.exit_code == 3
    assert not result.timed_out
    assert not result.truncated
    assert result.duration_ms >= 0


async def test_uncaught_exception_goes_to_stderr_with_nonzero_exit() -> None:
    result = await make_runner().run("raise ValueError('boom')\n")

    assert result.exit_code == 1
    assert "ValueError: boom" in result.stderr


async def test_infinite_loop_is_killed_at_the_timeout() -> None:
    started = time.monotonic()
    result = await make_runner(timeout_s=0.5).run("while True: pass\n")

    assert result.timed_out
    assert result.exit_code != 0
    assert time.monotonic() - started < 4


async def test_timeout_kills_the_whole_process_group() -> None:
    code = (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(p.pid, flush=True)\n"
        "p.wait()\n"
    )
    result = await make_runner(timeout_s=1).run(code)

    assert result.timed_out
    child = int(result.stdout.split()[0])
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("grandchild survived the timeout")


async def test_output_beyond_the_cap_is_truncated_with_a_marker() -> None:
    result = await make_runner(output_cap_kb=1).run("print('x' * 100_000)\n")

    assert result.truncated
    assert result.stdout.startswith("x" * 1024)
    assert result.stdout.count("x") == 1024
    assert "[output truncated at 1 KB]" in result.stdout
    assert not result.timed_out


async def test_stdin_is_passed_through() -> None:
    result = await make_runner().run("print(sum(int(x) for x in input().split()))\n", stdin="1 2 3\n")

    assert result.stdout == "6\n"


async def test_no_stdin_means_input_hits_eof_instead_of_hanging() -> None:
    result = await make_runner().run("input()\n")

    assert "EOFError" in result.stderr


async def test_only_the_standard_library_is_importable() -> None:
    result = await make_runner().run("import json, collections\nimport fastapi\n")

    assert result.exit_code != 0
    assert "ModuleNotFoundError" in result.stderr


async def test_backend_environment_is_not_visible() -> None:
    os.environ["RUNNER_TEST_SECRET"] = "s3cret"
    try:
        result = await make_runner().run("import os\nprint(dict(os.environ))\n")
    finally:
        del os.environ["RUNNER_TEST_SECRET"]

    assert "s3cret" not in result.stdout


async def test_cancelling_a_run_kills_it_and_a_new_run_can_start() -> None:
    runner = make_runner(timeout_s=30)
    first = asyncio.create_task(runner.run("import time\nprint('x', flush=True)\ntime.sleep(60)\n"))
    await asyncio.sleep(0.5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = await runner.run("print('second')\n")
    assert second.stdout == "second\n"


def test_startup_check_accepts_the_default_interpreter() -> None:
    assert check_interpreter(RunnerConfig()).endswith("python3")


def test_startup_check_rejects_a_missing_interpreter() -> None:
    with pytest.raises(ConfigError):
        check_interpreter(RunnerConfig(python="definitely-not-a-python"))


def test_startup_check_rejects_python_older_than_3_11(tmp_path: Path) -> None:
    fake = tmp_path / "old-python"
    fake.write_text("#!/bin/sh\necho 3 10\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    with pytest.raises(ConfigError, match="3.11"):
        check_interpreter(RunnerConfig(python=str(fake)))


async def test_a_background_child_holding_the_pipes_does_not_make_a_finished_run_time_out() -> None:
    code = "import subprocess\nsubprocess.Popen(['sleep', '60'])\nprint('done')\n"
    started = time.monotonic()
    result = await make_runner(timeout_s=10).run(code)

    assert not result.timed_out
    assert result.exit_code == 0
    assert result.stdout == "done\n"
    assert time.monotonic() - started < 5
