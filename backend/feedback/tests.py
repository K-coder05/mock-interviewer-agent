"""Candidate Test extraction: the executed tests the Candidate wrote, found in the code each Run
executed (syntax-tree analysis, no model).

Forms found: `assert` statements, calls under the main guard, printed calls (`print(f(x))`, at
module level or under the guard) and stdin inputs. Only statements the Run reached count: a
failing line is read from the traceback, later statements are dropped.

A test is verified when the Candidate stated its expected result: an assert always; anything else
when a comment next to the call, or something said within `SPOKEN_WINDOW_MS` of the Run, states
an expectation. Whether a comment or utterance states one is a keyword heuristic
(`EXPECTATION`), deliberately generous toward the Candidate. Traced tests are not found here:
the model tags them from the transcript at Report time.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from backend.db import Event

SPOKEN_WINDOW_MS = 30_000
SPOKEN_GRACE_MS = 5_000  # speech right after the Run starts still counts
EXPECTATION = re.compile(
    r"expect|should (?:be|return|give|print|output|get|equal)|->|→|=>|==|\bgives?\b|\breturns?\b"
    r"|\bequals?\b|\boutputs? (?:is|should)|\bis\s+-?\d",
    re.IGNORECASE,
)

Form = Literal["assert", "call", "printed_call", "stdin"]
Outcome = Literal["ok", "failed", "unknown"]


@dataclass(frozen=True)
class ExecutedTest:
    id: str
    form: Form
    source: str
    verified: bool
    outcome: Outcome
    """`failed` if the Run stopped on this statement; `unknown` if the Run timed out or no line
    could be read from its traceback."""
    t_ms: int
    """When the test was first run."""
    runs: int
    """How many Runs executed it."""


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left, *node.test.comparators]
    return any(isinstance(n, ast.Name) and n.id == "__name__" for n in names) and any(
        isinstance(n, ast.Constant) and n.value == "__main__" for n in names
    )


def _statements(body: Sequence[ast.stmt], in_guard: bool) -> list[tuple[ast.stmt, bool]]:
    """Top-level statements (and those inside the main guard) with whether they sit in it.
    The body of a `main` or `test*` function the top level calls counts as the guard's."""
    found: list[tuple[ast.stmt, bool]] = []
    for node in body:
        if _is_main_guard(node):
            assert isinstance(node, ast.If)
            found.extend(_statements(node.body, True))
        else:
            found.append((node, in_guard))
    called = {
        n.func.id
        for stmt, _ in found
        for n in ast.walk(stmt)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    for node in body:
        if (
            isinstance(node, ast.FunctionDef)
            and (node.name == "main" or node.name.startswith("test"))
            and node.name in called
        ):
            found.extend((stmt, True) for stmt in node.body)
    return found


def _calls(node: ast.AST | None) -> bool:
    return node is not None and any(isinstance(n, ast.Call) for n in ast.walk(node))


def _is_print(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"
    )


def _classify(node: ast.stmt, in_guard: bool) -> Form | None:
    if isinstance(node, ast.Assert):
        return "assert"
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _is_print(node.value):
            return "printed_call" if _calls_inside_print(node.value) else None
        # a bare call is a test only under the guard (module level it is usually setup)
        return "call" if in_guard else None
    if in_guard and isinstance(node, ast.Assign | ast.AnnAssign) and _calls(node.value):
        return "call"
    return None


def _calls_inside_print(call: ast.Call) -> bool:
    return any(_calls(arg) for arg in call.args)


def _comments(code: str) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _failing_line(run: Event) -> int | None:
    """The `main.py` line the Run's traceback ended on, if it stopped on an error."""
    if run.payload.get("exit_code") == 0 or run.payload.get("timed_out"):
        return None
    frames = re.findall(
        r'File "[^"]*main\.py", line (\d+), in (\S+)', str(run.payload.get("stderr", ""))
    )
    module = [int(n) for n, scope in frames if scope == "<module>"]
    return module[0] if module else None


def _said_expectation(events: Sequence[Event], t_ms: int) -> bool:
    return any(
        e.type == "utterance"
        and e.payload.get("speaker") == "user"
        and -SPOKEN_WINDOW_MS <= e.t_ms - t_ms <= SPOKEN_GRACE_MS
        and EXPECTATION.search(str(e.payload.get("text", "")))
        for e in events
    )


def extract_executed_tests(events: Sequence[Event]) -> list[ExecutedTest]:
    """Every distinct executed test across the Session's Runs, in order of first execution.
    The same statement run again (after an edit or not) is one test, with its latest outcome."""
    snapshots = {e.seq: e for e in events if e.type == "code_snapshot"}
    tests: dict[tuple[str, str], ExecutedTest] = {}
    for run in (e for e in events if e.type == "run"):
        seq = run.payload.get("snapshot_seq")
        snapshot = snapshots.get(seq) if isinstance(seq, int) else None
        found = _tests_in_run(events, run, str(snapshot.payload.get("code", "")) if snapshot else "")
        for form, source, verified, outcome in found:
            key = (form, source)
            previous = tests.get(key)
            tests[key] = ExecutedTest(
                id="",
                form=form,
                source=source,
                verified=verified or (previous.verified if previous else False),
                outcome=outcome,
                t_ms=previous.t_ms if previous else run.t_ms,
                runs=(previous.runs if previous else 0) + 1,
            )
    return [_with_id(t, i) for i, t in enumerate(tests.values(), 1)]


def _with_id(test: ExecutedTest, number: int) -> ExecutedTest:
    return ExecutedTest(**{**test.__dict__, "id": f"x{number}"})


def _tests_in_run(
    events: Sequence[Event], run: Event, code: str
) -> list[tuple[Form, str, bool, Outcome]]:
    found: list[tuple[Form, str, bool, Outcome]] = []
    spoken = _said_expectation(events, run.t_ms)
    stdin = str(run.payload.get("stdin") or "")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None  # a Run of broken code executed nothing, but its stdin was still chosen
    if tree is not None:
        failing = _failing_line(run)
        comments = _comments(code)
        lines = code.splitlines()
        for node, in_guard in _statements(tree.body, False):
            form = _classify(node, in_guard)
            if form is None:
                continue
            end = node.end_lineno or node.lineno
            if failing is not None and node.lineno > failing:
                continue  # never reached
            outcome: Outcome = (
                "unknown" if run.payload.get("timed_out") or (
                    run.payload.get("exit_code") != 0 and failing is None
                ) else "ok"
            )
            if failing is not None and node.lineno <= failing <= end:
                outcome = "failed"
            nearby = [comments[n] for n in range(node.lineno, end + 1) if n in comments]
            above = node.lineno - 1  # a comment on its own line directly above also counts
            if above in comments and lines[above - 1].lstrip().startswith("#"):
                nearby.append(comments[above])
            verified = form == "assert" or spoken or any(EXPECTATION.search(c) for c in nearby)
            source = "\n".join(lines[node.lineno - 1 : end]).strip()
            found.append((form, source, verified, outcome))
    if stdin.strip() and ("input" in code or "stdin" in code):
        found.append(("stdin", stdin.strip(), spoken, "ok" if run.payload.get("exit_code") == 0 else "unknown"))
    return found
