r"""Plan 00200 Phase 1 — the lint QA gate must not report PASSED while blind.

``untracked/qa/lint.json`` was recording ``total_files_checked: 0,
total_violations: 0, passed: true`` while ruff over the identical scope reported
47 violations. Three things composed to produce that:

1. ``scripts/venv-include.bash:81`` — ``ensure_venv()`` writes its success
   banner to **stdout**. Its own error branches at ``:91-95`` correctly use
   ``>&2``, so the inconsistency lives inside one function.
2. ``venv_tool()`` calls ``ensure_venv`` on EVERY invocation, so the banner
   precedes every tool's output.
3. ``scripts/qa/run_lint.sh:35`` redirects stdout into the file it then parses
   as JSON, so the raw capture begins with an ANSI banner and ``json.loads``
   raises.

``run_lint.sh:55-57`` then swallowed the ``JSONDecodeError`` into
``ruff_output = []``, and ``:82`` sets ``passed = len(violations) == 0`` — so an
unparseable capture became a green gate.

Note ``2>&1`` alone was never the root cause: the banner is on **stdout**, which
is redirected regardless. Both the banner destination and the swallow must be
fixed, and both are pinned here.

These tests deliberately do NOT invoke ``run_lint.sh`` end to end — it runs
``ruff check --fix``, which would rewrite the working tree as a side effect of
running the suite. Instead they pin the two mechanisms independently.

Behavioural tests — they source the real bash and execute the real embedded
parser.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_INCLUDE = REPO_ROOT / "scripts" / "venv-include.bash"
RUN_LINT_SH = REPO_ROOT / "scripts" / "qa" / "run_lint.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 120

# The embedded parser in run_lint.sh, delimited by a quoted heredoc.
_PARSER_BLOCK = re.compile(
    r"python3\s*<<\s*'EOF'\s*>\s*\"\$\{OUTPUT_FILE\}\"\n(?P<body>.*?)\nEOF\n",
    re.DOTALL,
)

# A realistic corrupted capture: the ANSI venv banner, then ruff's real JSON.
_ANSI_BANNER = "\x1b[0;32m✓\x1b[0m Venv exists: /workspace/untracked/venv-x\n"
_RUFF_JSON = (
    '[{"filename": "src/example.py", "code": "F401", '
    '"message": "unused import", "location": {"row": 1, "column": 1}}]'
)


def test_ensure_venv_does_not_write_to_stdout() -> None:
    """``ensure_venv`` must keep diagnostics on stderr.

    Anything it prints to stdout lands inside every ``venv_tool`` capture. This
    is the root cause, and fixing it protects every current and future caller —
    not just run_lint.sh, which merely happened to parse stdout as JSON.
    """
    result = subprocess.run(
        [BASH, "-c", f'source "{VENV_INCLUDE}" >/dev/null 2>&1; ensure_venv'],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, f"ensure_venv failed: {result.stderr.strip()}"
    assert result.stdout == "", (
        "ensure_venv wrote to stdout, which corrupts every venv_tool capture "
        f"that redirects stdout to a parsed file. Got: {result.stdout!r}. "
        "Diagnostics belong on stderr (>&2), as the sibling error branches "
        "in the same function already do."
    )


def _extract_parser(script: str) -> str:
    match = _PARSER_BLOCK.search(script)
    assert match is not None, (
        "Could not locate the embedded python parser in run_lint.sh. If it was "
        "restructured, update _PARSER_BLOCK — do not delete this test."
    )
    return match.group("body")


def test_lint_parser_fails_loudly_on_unparseable_capture(tmp_path: Path) -> None:
    """A capture that cannot be parsed must FAIL the gate, never pass it.

    Feeds the gate's own parser a realistically-corrupted capture (ANSI banner
    followed by valid ruff JSON) and requires a non-zero exit. Reading "I could
    not parse this" as "there are no violations" is precisely the error-hiding
    pattern this repo ships a blocking handler and a dedicated auditor against.
    """
    parser = _extract_parser(RUN_LINT_SH.read_text(encoding="utf-8"))

    raw_dir = tmp_path / "untracked" / "qa"
    raw_dir.mkdir(parents=True)
    (raw_dir / "lint.json.raw").write_text(_ANSI_BANNER + _RUFF_JSON, encoding="utf-8")

    result = subprocess.run(
        ["python3", "-c", parser],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode != 0, (
        "The lint gate's parser accepted an unparseable capture instead of "
        f"failing. stdout was: {result.stdout.strip()[:400]}. A gate that "
        "cannot tell 'clean' from 'broken' manufactures false confidence."
    )


def test_lint_parser_reports_violations_from_a_clean_capture(tmp_path: Path) -> None:
    """Sanity control: given uncorrupted ruff JSON, the gate must NOT pass.

    Without this, a parser that failed unconditionally would satisfy the test
    above while being just as useless.
    """
    parser = _extract_parser(RUN_LINT_SH.read_text(encoding="utf-8"))

    raw_dir = tmp_path / "untracked" / "qa"
    raw_dir.mkdir(parents=True)
    (raw_dir / "lint.json.raw").write_text(_RUFF_JSON, encoding="utf-8")

    result = subprocess.run(
        ["python3", "-c", parser],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, f"parser errored on valid JSON: {result.stderr.strip()}"
    assert (
        '"total_violations": 1' in result.stdout
    ), f"Expected the single seeded violation to be reported. Got: {result.stdout.strip()[:400]}"
    assert '"passed": false' in result.stdout, "A capture with a violation must not report passed"
