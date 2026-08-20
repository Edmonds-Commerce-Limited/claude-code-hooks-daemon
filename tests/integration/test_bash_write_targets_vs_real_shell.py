"""Differential test: `get_bash_write_targets` vs what bash ACTUALLY writes.

Plan 00260. This exists because of what it FOUND, not as belt-and-braces.

`get_bash_write_targets` had 44 unit tests, a full QA pass and a careful
read-through, and still carried four defects. Running the commands through a
real shell and comparing surfaced all four in one pass:

- `cp -t DEST src` returned the SOURCE — a file the command reads, reported as
  one it writes.
- `cp a.py somedir` returned nothing, while bash wrote `somedir/a.py`. Copying
  a file INTO a guarded directory is the obvious way to reach one without ever
  naming it.
- a heredoc body containing prose yielded a phantom target.
- `&>` was missed entirely.

Hand-written tests encode what the author already believes; this encodes what
the shell does. That is the difference that matters, and it is why this runs in
CI rather than living in a scratch directory (the project's defence-before-fix
rule: the defect is the symptom, the missing guard is the bug).

**Scanned with `include_heredoc_bodies=False`, deliberately.** That flag is a
documented SUPERSET — a body is data, and prose containing a redirect is
indistinguishable from a script, so it can name files the command never writes.
Its cost is pinned in the unit tests; the strict contract is what can be held
to exact equality with a real shell, and is.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.utils import get_bash_write_targets

# `{S}` is substituted with the sandbox directory.
_CASES: list[tuple[str, str]] = [
    ("plain redirect", "echo hi > {S}/a.txt"),
    ("append to existing", "echo hi >> {S}/a.txt"),
    ("noclobber override", "echo hi >| {S}/b.txt"),
    ("both-streams redirect", "echo hi &> {S}/c.txt"),
    ("both-streams append", "echo hi &>> {S}/c.txt"),
    ("stderr dup writes no file", "echo hi 2>&1"),
    ("numbered fd redirect", "echo hi 3> {S}/fd.txt"),
    ("tee single operand", "echo hi | tee {S}/t1.txt"),
    ("tee two operands", "echo hi | tee {S}/t2.txt {S}/t3.txt"),
    ("tee append flag", "echo hi | tee -a {S}/t4.txt"),
    ("tee double dash", "echo hi | tee -- {S}/t5.txt"),
    ("cp two operands", "cp {S}/src.txt {S}/cp1.txt"),
    ("mv two operands", "mv {S}/src2.txt {S}/mv1.txt"),
    ("cp into a directory", "cp {S}/src.txt {S}/adir"),
    ("cp -t directory", "cp -t {S}/adir {S}/src.txt"),
    ("cp three operands", "cp {S}/src.txt {S}/src2.txt {S}/adir"),
    ("subshell redirect", "(echo hi) > {S}/sub.txt"),
    ("compound with &&", "echo a > {S}/x1.txt && echo b > {S}/x2.txt"),
    ("semicolon separated", "echo a > {S}/y1.txt; echo b > {S}/y2.txt"),
    ("quoted path with a space", 'echo hi > "{S}/sp ace.txt"'),
    ("prose containing an arrow", "echo 'the arrow > file thing'"),
    ("read is not a write", "cat {S}/src.txt"),
    ("grep is not a write", "grep hi {S}/src.txt"),
    ("heredoc write", "cat > {S}/hd.txt <<'EOF'\nbody line\nEOF"),
    ("heredoc body with an arrow", "cat > {S}/hd2.txt <<'EOF'\nroute out > somewhere\nEOF"),
    ("heredoc body with a stray quote", "cat > {S}/hd3.txt <<'EOF'\nhe said \"hi\nEOF"),
]

# Cases needing a tool that may be absent. A missing tool writes nothing, which
# would read as an overclaim rather than as the skip it really is.
_TOOL_CASES: list[tuple[str, str, str]] = [
    ("install with a mode flag", "install", "install -m 644 {S}/src.txt {S}/inst.txt"),
    ("dd output operand", "dd", "dd if={S}/src.txt of={S}/dd1.img status=none"),
]


def _seed(sandbox: Path) -> None:
    (sandbox / "adir").mkdir()
    (sandbox / "src.txt").write_text("seed\n")
    (sandbox / "src2.txt").write_text("seed2\n")
    (sandbox / "a.txt").write_text("existing\n")


def _snapshot(sandbox: Path) -> dict[str, tuple[int, int]]:
    """Size and mtime of every file, so a rewrite in place is still detected."""
    found: dict[str, tuple[int, int]] = {}
    for path in sandbox.rglob("*"):
        if path.is_file():
            stat = path.stat()
            found[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return found


def _run_case(command: str, sandbox: Path) -> tuple[set[str], set[str]]:
    """Return (what bash actually wrote, what the accessor predicted).

    SECURITY: the command list is built from this module's own literals and a
    pytest sandbox path, never from user input, and no shell string is passed
    to a shell interpreter beyond the deliberate `bash -c` under test. Running
    a real shell IS the point of the file.
    """
    before = _snapshot(sandbox)
    subprocess.run(
        ["bash", "-c", command],
        cwd=str(sandbox),
        capture_output=True,
        check=False,
    )
    after = _snapshot(sandbox)

    actual = {path for path in after if after[path] != before.get(path)}
    predicted = set(
        get_bash_write_targets(
            {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(sandbox)}
        )
    )
    return actual, predicted


@pytest.mark.parametrize(("label", "template"), _CASES, ids=[case[0] for case in _CASES])
def test_prediction_matches_a_real_shell(label: str, template: str, tmp_path: Path) -> None:
    """Exact equality: every predicted path written, every written path predicted."""
    _seed(tmp_path)
    command = template.format(S=tmp_path)

    actual, predicted = _run_case(command, tmp_path)

    assert predicted - actual == set(), (
        f"{label}: OVERCLAIM — predicted a path bash did not write. This is the "
        f"failure the conservative contract forbids: a path-keyed guard would "
        f"judge a file that was never written. actually wrote {sorted(actual)}"
    )
    assert actual - predicted == set(), (
        f"{label}: MISS — bash wrote a path we did not predict. Fails safe, but "
        f"a guard keyed on that path will not fire. predicted {sorted(predicted)}"
    )


@pytest.mark.parametrize(
    ("label", "tool", "template"), _TOOL_CASES, ids=[case[0] for case in _TOOL_CASES]
)
def test_prediction_matches_a_real_shell_for_optional_tools(
    label: str, tool: str, template: str, tmp_path: Path
) -> None:
    """Same check, skipped rather than failed when the tool is not installed."""
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} is not installed; a missing tool would read as an overclaim")

    _seed(tmp_path)
    command = template.format(S=tmp_path)

    actual, predicted = _run_case(command, tmp_path)

    assert predicted - actual == set(), f"{label}: OVERCLAIM, actually wrote {sorted(actual)}"
    assert actual - predicted == set(), f"{label}: MISS, predicted {sorted(predicted)}"
