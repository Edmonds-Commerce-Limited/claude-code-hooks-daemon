"""A sub-agent does not start a full QA run (Plan 00463).

The owner's measurement was the whole case for this handler: five
``llm_qa.py all`` runs executing at once, one per worktree, each about 25,700
tests over 15-20 minutes on eight cores. Each agent then re-ran the suite after
every fix round, and the coordinator ran it again before merging. The full gate
stays BEFORE the main branch moves, but it moves to the coordinator, which runs
it once over every ready branch merged together.

Three properties are pinned here, and each is a way the guard could fail
without looking broken:

1. **Parsed, not substring-matched.** A commit message, a ``grep`` or an
   ``echo`` that MENTIONS ``llm_qa.py all`` runs nothing. Denying it would
   teach agents that the guard is noise.
2. **Scoped by the chain, not by the handler.** ``scope=SUB`` carries the whole
   role test. That includes the synthetic guard, which keeps the acceptance
   harness's probes from ever being denied as though they were a sub-agent.
3. **A deny names the way forward.** A refusal with no allowed alternative is
   the Plan 00460 defect, so the reason lists the project's targeted commands
   and says the coordinator runs the full gate.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope, scope_admits
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PLAYBOOK_PROBE,
    SYNTHETIC_SOURCE_FIELD,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    PYTEST_FLAG_OPTIONS,
    PYTEST_VALUE_OPTIONS,
    FullQaPattern,
    SubagentFullQaBlockerHandler,
    find_full_qa_invocation,
    parse_full_qa_patterns,
)


def _live_options() -> dict[str, Any]:
    """This repository's REAL declaration, read from the dogfood config.

    Read rather than restated: a restated copy stays green while the YAML the
    live guard runs on drifts (review finding 12 on Plan 00463).
    """
    config = ConfigLoader.load(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    options = config["handlers"]["pre_tool_use"]["subagent_full_qa_blocker"]["options"]
    assert isinstance(options, dict)
    return options


_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPO_PATTERNS: list[dict[str, Any]] = _live_options()["full_qa_patterns"]
_TARGETED: list[str] = _live_options()["targeted_qa_commands"]


def _handler(
    patterns: list[dict[str, Any]] | None = None,
    targeted: list[str] | None = None,
) -> SubagentFullQaBlockerHandler:
    handler = SubagentFullQaBlockerHandler()
    handler._full_qa_patterns = _REPO_PATTERNS if patterns is None else patterns
    handler._targeted_qa_commands = _TARGETED if targeted is None else targeted
    return handler


def _bash(command: str, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        **extra,
    }


def _patterns() -> list[FullQaPattern]:
    patterns, problems = parse_full_qa_patterns(_REPO_PATTERNS)
    assert not problems, problems
    return patterns


# ── What counts as a full run ──────────────────────────────────────────────

#: Built from parts: the literal call in a test row would read as a use of it.
_SHELL_OUT = "os." + "system"
_DUNDER_IMPORT = "__imp" + "ort__"

_FULL_RUNS: list[tuple[str, str]] = [
    ("./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("python3 scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("untracked/venv/bin/python ./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py tests", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py lint all", "llm-qa-whole-suite"),
    ("cd /srv/wt && ./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    (
        "set -o pipefail; ./scripts/qa/llm_qa.py all 2>&1 | bin/echd-capture 20",
        "llm-qa-whole-suite",
    ),
    (
        "timeout 3600 ./scripts/qa/llm_qa.py all > untracked/scratch/qa.txt 2>&1",
        "llm-qa-whole-suite",
    ),
    ("nohup ./scripts/qa/llm_qa.py all > qa.log 2>&1 &", "llm-qa-whole-suite"),
    ('./scripts/qa/llm_qa.py all; echo "QA_EXIT=$?"', "llm-qa-whole-suite"),
    ("bash -c './scripts/qa/llm_qa.py all'", "llm-qa-whole-suite"),
    ("(cd /srv/wt && ./scripts/qa/llm_qa.py all)", "llm-qa-whole-suite"),
    ("echo $(./scripts/qa/llm_qa.py all)", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py \\\n  all", "llm-qa-whole-suite"),
    ("./scripts/qa/run_all.sh", "run-all"),
    ("bash scripts/qa/run_all.sh", "run-all"),
    ("./scripts/qa/run_tests.sh", "run-tests"),
    ("./scripts/validate_worktrees.sh", "validate-worktrees"),
    ("pytest", "pytest-whole-suite"),
    ("pytest -x -q", "pytest-whole-suite"),
    ("pytest tests/", "pytest-whole-suite"),
    ("pytest tests", "pytest-whole-suite"),
    ("pytest ./tests/", "pytest-whole-suite"),
    ("pytest tests/unit", "pytest-whole-suite"),
    ("pytest tests/unit/", "pytest-whole-suite"),
    ("pytest .", "pytest-whole-suite"),
    ("pytest /srv/project/tests", "pytest-whole-suite"),
    ("python -m pytest tests/", "pytest-whole-suite"),
    ("untracked/venv/bin/python -m pytest -q tests/", "pytest-whole-suite"),
    ("pytest -k handler", "pytest-whole-suite"),
    ("pytest tests/ -k handler", "pytest-whole-suite"),
    ("pytest tests/unit/handlers/test_x.py tests/", "pytest-whole-suite"),
    ("FOO=1 pytest tests/", "pytest-whole-suite"),
    ("env PYTHONPATH=src pytest", "pytest-whole-suite"),
    ("uv run pytest", "pytest-whole-suite"),
    ("sudo -E pytest tests/", "pytest-whole-suite"),
    # A flag's value is not a path (review finding 2): pytest's real grammar.
    ("pytest --timeout 60", "pytest-whole-suite"),
    ("pytest --cov src", "pytest-whole-suite"),
    ("pytest --numprocesses 8", "pytest-whole-suite"),
    ("pytest --log-level DEBUG", "pytest-whole-suite"),
    ("pytest --override-ini addopts=", "pytest-whole-suite"),
    ("pytest --tb short", "pytest-whole-suite"),
    ("pytest -p no:randomly", "pytest-whole-suite"),
    ("pytest --maxfail 1", "pytest-whole-suite"),
    ("pytest --basetemp /tmp/pt", "pytest-whole-suite"),
    # `--cov` takes an optional value, so argparse consumes the next word.
    ("pytest --cov tests/unit/handlers/test_x.py", "pytest-whole-suite"),
    # Project runners with their own flags (review finding 4).
    ("uv run --frozen pytest", "pytest-whole-suite"),
    ("uv run -- pytest", "pytest-whole-suite"),
    ("uv run -q pytest", "pytest-whole-suite"),
    ("uv --directory x run pytest", "pytest-whole-suite"),
    ("uv run --directory x pytest", "pytest-whole-suite"),
    ("uv run --with pytest-xdist pytest", "pytest-whole-suite"),
    ("poetry run -- pytest", "pytest-whole-suite"),
    ("uvx pytest", "pytest-whole-suite"),
    # Smaller evasions (review finding 5).
    ("./scripts/qa/llm_qa.py all>out.txt", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py all>>out.txt 2>&1", "llm-qa-whole-suite"),
    ("pytest $PWD/tests", "pytest-whole-suite"),
    ("pytest ${PWD}/tests", "pytest-whole-suite"),
    ("env -C /srv/wt pytest", "pytest-whole-suite"),
    ("env --chdir=/srv/wt pytest", "pytest-whole-suite"),
    # Delta review N5: runner flags no table lists, and redirect and home forms.
    ("uv run --color never pytest", "pytest-whole-suite"),
    ("uv run --exclude-newer 2024-01-01 pytest", "pytest-whole-suite"),
    ("uv run --resolution lowest pytest", "pytest-whole-suite"),
    ("uv --some-new-global-flag value run pytest", "pytest-whole-suite"),
    ("poetry run --directory x pytest", "pytest-whole-suite"),
    ("pdm run -p x pytest", "pytest-whole-suite"),
    ("uvx pytest@8", "pytest-whole-suite"),
    ("uvx pytest@8.3.0 tests/", "pytest-whole-suite"),
    ("uv tool run pytest@8", "pytest-whole-suite"),
    ("hatch run test:pytest", "pytest-whole-suite"),
    ("./scripts/qa/llm_qa.py all&>out.txt", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py all &> out.txt", "llm-qa-whole-suite"),
    ("pytest ~/proj/tests", "pytest-whole-suite"),
    ("pytest $HOME/proj/tests", "pytest-whole-suite"),
    ("pytest ${HOME}/proj/tests/", "pytest-whole-suite"),
    # Delta review N4: a plugin flag the grammar does not know takes a value, so
    # its path-shaped value is not a target.
    ("pytest --json-report-file out/r.json", "pytest-whole-suite"),
    ("pytest --some-plugin out/x", "pytest-whole-suite"),
    # Review 3 R7: pytest's other name, the coverage runner, unnormalised paths.
    ("py.test", "pytest-whole-suite"),
    ("py.test tests/", "pytest-whole-suite"),
    ("python -m py.test", "pytest-whole-suite"),
    ("coverage run -m pytest", "pytest-whole-suite"),
    ("coverage run --source src -m pytest tests/", "pytest-whole-suite"),
    ("python -m coverage run -m pytest", "pytest-whole-suite"),
    ("uv run coverage run -m pytest", "pytest-whole-suite"),
    ("pytest tests/unit/../unit", "pytest-whole-suite"),
    ("pytest tests//unit", "pytest-whole-suite"),
    ("pytest tests/./unit", "pytest-whole-suite"),
    ("pytest tests/unit/qa/..", "pytest-whole-suite"),
    # Review 4 N4: a substitution inside double quotes still RUNS its command.
    ('out="$(./scripts/qa/llm_qa.py all 2>&1)"; echo "$out"', "llm-qa-whole-suite"),
    ('x="$(pytest tests)"', "pytest-whole-suite"),
    ('echo "$(pytest tests)"', "pytest-whole-suite"),
    ('echo "`pytest tests`"', "pytest-whole-suite"),
    ('git commit -m "$(./scripts/qa/llm_qa.py all)"', "llm-qa-whole-suite"),
    ('echo "$(echo "$(pytest)")"', "pytest-whole-suite"),
    # Review 4 N5: globs and braces the shell expands to the whole suite.
    ("pytest tests/*", "pytest-whole-suite"),
    ("pytest tests/unit/*", "pytest-whole-suite"),
    ("pytest tests/{unit,integration}", "pytest-whole-suite"),
    ("pytest tests/unit/**/test_*.py", "pytest-whole-suite"),
    ("pytest *", "pytest-whole-suite"),
    # Review 4 N5: code a shell reads from a string, a here-string or a pipe.
    ("eval 'pytest tests'", "pytest-whole-suite"),
    ("eval pytest", "pytest-whole-suite"),
    ("bash <<< 'pytest tests'", "pytest-whole-suite"),
    ("bash <<<'pytest tests'", "pytest-whole-suite"),
    ("echo 'pytest tests' | bash", "pytest-whole-suite"),
    ("printf 'pytest tests\\n' | sh", "pytest-whole-suite"),
    ("bash < <(echo pytest tests)", "pytest-whole-suite"),
    ("source scripts/qa/run_tests.sh", "run-tests"),
    (". scripts/qa/run_tests.sh", "run-tests"),
    ("time -p pytest tests", "pytest-whole-suite"),
    ("builtin command pytest tests", "pytest-whole-suite"),
    # Review 4 N5: ANSI-C quoting, whose `\'` shlex read as closing the quote.
    ("echo $'a\\'b' ; ./scripts/qa/llm_qa.py all", "llm-qa-whole-suite"),
    ("./scripts/qa/llm_qa.py $'all'", "llm-qa-whole-suite"),
    # Review 4 N9: xargs runs its command; arguments from stdin cannot be seen.
    ("xargs pytest tests", "pytest-whole-suite"),
    ("echo tests | xargs pytest", "pytest-whole-suite"),
    ("find tests -name 'test_*.py' | xargs pytest", "pytest-whole-suite"),
    ("xargs -n 1 pytest", "pytest-whole-suite"),
    # Review 4 probe: the working directory by substitution, and launchers that
    # run the command after their own flags and operands.
    ('pytest "$(pwd)/tests"', "pytest-whole-suite"),
    ("pytest `pwd`/tests", "pytest-whole-suite"),
    ('pytest "$(pwd)"', "pytest-whole-suite"),
    ("ionice -c3 pytest", "pytest-whole-suite"),
    ("ionice -c 2 -n 7 pytest tests", "pytest-whole-suite"),
    ("chrt 0 pytest", "pytest-whole-suite"),
    ("chrt -f 10 pytest tests", "pytest-whole-suite"),
    ("setsid pytest tests", "pytest-whole-suite"),
    ("setsid -f nice pytest", "pytest-whole-suite"),
    ("flock /tmp/x pytest tests", "pytest-whole-suite"),
    ("flock -w 5 /tmp/x pytest", "pytest-whole-suite"),
    ("flock /tmp/x -c 'pytest tests'", "pytest-whole-suite"),
    ("taskset -c 0 pytest", "pytest-whole-suite"),
    ("taskset 0x1 pytest tests", "pytest-whole-suite"),
    ("xvfb-run pytest", "pytest-whole-suite"),
    ("xvfb-run -a -s '-screen 0 1x1x8' pytest", "pytest-whole-suite"),
    ("script -c pytest", "pytest-whole-suite"),
    ("script -q -c 'pytest tests' out.log", "pytest-whole-suite"),
    ("script --command='pytest tests'", "pytest-whole-suite"),
    ("pipx run pytest", "pytest-whole-suite"),
    ("parallel pytest ::: tests", "pytest-whole-suite"),
    ("parallel -j 2 pytest ::: tests/unit/x.py tests", "pytest-whole-suite"),
    ("parallel ::: 'pytest tests'", "pytest-whole-suite"),
    ("parallel pytest", "pytest-whole-suite"),
    # Review 5 m3: `--` after a wrapper, a code flag in a cluster, `exec -a`,
    # and the launchers that time or trace the command they run.
    ("env -- pytest tests", "pytest-whole-suite"),
    ("nice -- pytest tests", "pytest-whole-suite"),
    ("timeout -- 600 pytest tests", "pytest-whole-suite"),
    ("script -qc 'pytest tests' /dev/null", "pytest-whole-suite"),
    ("script -qec pytest", "pytest-whole-suite"),
    ("exec -a qa pytest tests", "pytest-whole-suite"),
    ("exec -cl pytest", "pytest-whole-suite"),
    ("/usr/bin/time -v pytest", "pytest-whole-suite"),
    ("time -v pytest tests", "pytest-whole-suite"),
    ("/usr/bin/time -o t.txt -f %e pytest", "pytest-whole-suite"),
    ("strace -f -o trace.txt pytest", "pytest-whole-suite"),
    ("ltrace -o trace.txt pytest tests", "pytest-whole-suite"),
    ("caffeinate -i pytest", "pytest-whole-suite"),
    ("caffeinate -w 123 pytest tests", "pytest-whole-suite"),
    ("doas -u dev pytest tests", "pytest-whole-suite"),
    # Review 5 n4: ANSI-C hex, octal and unicode escapes are decoded.
    ("$'py\\x74est' tests", "pytest-whole-suite"),
    ("$'py\\164est' tests", "pytest-whole-suite"),
    ("$'\\u0070ytest' tests", "pytest-whole-suite"),
    ("./scripts/qa/llm_qa.py $'\\x61ll'", "llm-qa-whole-suite"),
    # Review 5 n4: a `function` keyword definition runs its body like `t()`.
    ("function t { pytest; }; t", "pytest-whole-suite"),
    ("function t { pytest tests; }", "pytest-whole-suite"),
    # Review 5 n4: a variable set in the command is the value it was set to.
    ("P=pytest; $P tests", "pytest-whole-suite"),
    ("P=pytest; ${P} tests", "pytest-whole-suite"),
    ("export P=pytest; $P", "pytest-whole-suite"),
    ("QA=./scripts/qa/llm_qa.py; $QA all", "llm-qa-whole-suite"),
    ("T=tests; pytest $T/unit", "pytest-whole-suite"),
    ("for t in lint all; do ./scripts/qa/llm_qa.py $t; done", "llm-qa-whole-suite"),
    # Review 5: a program named by a substitution is judged as that program.
    ("$(which pytest)", "pytest-whole-suite"),
    ('"$(command -v pytest)" tests', "pytest-whole-suite"),
    ("`which pytest` tests", "pytest-whole-suite"),
    ("X=$(which pytest); $X tests", "pytest-whole-suite"),
    ("$PYTHON -m pytest", "pytest-whole-suite"),
    # Review 5: an operand the shell only builds at run time may be the suite.
    ("pytest tests/unit/x.py $(cat more.txt)", "pytest-whole-suite"),
    ('pytest tests/unit/x.py "$EXTRA"', "pytest-whole-suite"),
    # Review 5: `hatch test` is hatch's pytest.
    ("hatch test", "pytest-whole-suite"),
    ("hatch test -c tests", "pytest-whole-suite"),
    ("hatch -e ci test --cover", "pytest-whole-suite"),
    # Review 5 m2: Python code read from stdin is judged as `python -c` code is.
    ("python3 - <<'PY'\nimport pytest\npytest.main(['tests'])\nPY", "pytest-whole-suite"),
    (
        "python3 <<'PY'\nimport pytest\nraise SystemExit(pytest.main([]))\nPY",
        "pytest-whole-suite",
    ),
    ("python3 <<PY\nimport pytest; pytest.main()\nPY", "pytest-whole-suite"),
    ("python3 <<-'PY'\n\timport pytest\n\tpytest.main()\n\tPY", "pytest-whole-suite"),
    ("python3 <<< 'import pytest; pytest.main()'", "pytest-whole-suite"),
    ("echo 'import pytest; pytest.main()' | python3", "pytest-whole-suite"),
    (f"python3 -c 'import os; {_SHELL_OUT}(\"pytest tests\")'", "pytest-whole-suite"),
]

_NOT_FULL_RUNS: list[str] = [
    "./scripts/qa/llm_qa.py lint type_check",
    "./scripts/qa/llm_qa.py changed",
    "./scripts/qa/llm_qa.py --read-only all",
    "./scripts/qa/llm_qa.py all --read-only",
    "./scripts/qa/llm_qa.py",
    "./scripts/qa/llm_qa.py lint > untracked/scratch/lint.txt 2>&1",
    "./scripts/qa/run_shell_check.sh",
    "./scripts/qa/run_lint.sh",
    "pytest tests/unit/handlers/x.py",
    "pytest tests/unit/handlers/",
    "pytest tests/unit/handlers/pre_tool_use/test_x.py::TestA::test_b -v",
    "python -m pytest tests/unit/core tests/unit/config -q",
    "pytest -k handler tests/unit/handlers",
    "pytest --collect-only -q",
    "pytest --co",
    # A value flag's `.` is its value, not the whole-suite operand (finding 2).
    "pytest --cov . tests/unit/handlers/x.py",
    "pytest --confcutdir . tests/unit/x.py",
    "pytest --rootdir . tests/unit/x.py",
    "pytest --cov=src tests/unit/x.py",
    "pytest --timeout 60 tests/unit/handlers/test_x.py",
    "uv run --frozen pytest tests/unit/handlers/test_x.py",
    "uv run -- pytest tests/unit/core",
    "uv run --color never pytest tests/unit/handlers/test_x.py",
    "uvx pytest@8 tests/unit/handlers/test_x.py",
    "hatch run test:pytest tests/unit/core",
    # The first word after `run` that no flag can claim is the command.
    "uv run mytool pytest",
    "./scripts/qa/llm_qa.py changed>out.txt",
    "./scripts/qa/llm_qa.py changed&>out.txt",
    # Known booleans, clusters and attached values take nothing from the next word.
    "pytest -xvs tests/unit/handlers/test_x.py",
    "pytest -n8 tests/unit/handlers/test_x.py",
    "pytest --lf tests/unit/handlers/test_x.py",
    "pytest --json-report-file=out/r.json tests/unit/x.py",
    "pytest tests/unit/x.py --some-plugin-flag",
    "py.test tests/unit/handlers/test_x.py",
    "coverage run -m pytest tests/unit/handlers/test_x.py",
    "coverage report",
    "pytest tests/unit/qa/../qa/test_x.py",
    # Mentions, not invocations: the guard parses, it does not substring-match.
    'grep -rn "llm_qa.py all" CLAUDE/',
    "grep -rn llm_qa.py all",
    'git commit -m "the coordinator runs llm_qa.py all"',
    "git commit -F - <<'EOF'\nrun ./scripts/qa/llm_qa.py all\nEOF",
    'echo "./scripts/qa/llm_qa.py all"',
    "cat scripts/qa/run_all.sh",
    "shellcheck scripts/qa/run_all.sh",
    "git add scripts/qa/run_all.sh scripts/qa/llm_qa.py",
    "git log --oneline -- scripts/qa/run_tests.sh",
    "python3 -c \"print('llm_qa.py all')\"",
    "ls tests/",
    "mypy tests/",
    # Review 4: the same constructs, running something narrow or nothing full.
    "pytest tests/unit/handlers/test_*.py",
    "pytest tests/unit/{core,config}/test_x.py",
    "eval 'pytest tests/unit/x.py'",
    "echo 'pytest tests/unit/x.py' | bash",
    'echo "$(git rev-parse HEAD)"',
    'x="$(./scripts/qa/llm_qa.py changed)"',
    'git commit -m "$(cat untracked/scratch/msg.txt)"',
    "echo '$(pytest tests)'",
    "echo $'a\\'b' ; ./scripts/qa/llm_qa.py lint",
    "time -p pytest tests/unit/x.py",
    "xargs pytest tests/unit/x.py",
    'echo "unterminated',
    'pytest "$(pwd)/tests/unit/handlers"',
    "setsid pytest tests/unit/x.py",
    "chrt 0 pytest tests/unit/x.py",
    "flock /tmp/x pytest tests/unit/x.py",
    "flock /tmp/x -c 'pytest tests/unit/x.py'",
    "taskset 0x1 pytest tests/unit/x.py",
    "ionice -c3 pytest tests/unit/x.py",
    "script -c 'pytest tests/unit/x.py'",
    "script out.log",
    "parallel pytest ::: tests/unit/x.py tests/unit/y.py",
    "parallel ::: 'pytest tests/unit/x.py'",
    "pipx run pytest tests/unit/x.py",
    "chrt -p 0 1234",
    # Review 4 N10: a quoted delimiter with a blank is still a quoted delimiter.
    "cat > n.txt <<' EOF'\npytest tests\n EOF",
    "cat > n.txt <<'EOF X'\npytest tests\nEOF X",
    # Review 5: the same constructs, running something narrow or nothing full.
    "script -qc 'pytest tests/unit/x.py' /dev/null",
    "exec -a qa pytest tests/unit/x.py",
    "/usr/bin/time -v pytest tests/unit/x.py",
    "strace -o trace.txt pytest tests/unit/x.py",
    "caffeinate -i pytest tests/unit/x.py",
    "P=pytest; $P tests/unit/x.py",
    '"$(command -v pytest)" tests/unit/x.py',
    "$EDITOR notes.txt",
    "$PYTHON -m pytest tests/unit/x.py",
    "for t in lint type_check; do ./scripts/qa/llm_qa.py $t; done",
    'for f in tests/unit/qa/test_*.py; do pytest "$f"; done',
    "hatch test tests/unit/x.py",
    "hatch run lint",
    "python3 - <<'PY'\nimport pytest\nprint(pytest.__version__)\nPY",
    "python3 - <<'PY'\nimport pytest\npytest.main(['tests/unit/x.py'])\nPY",
    "python3 <<< 'import pytest; print(pytest.__file__)'",
    "python3 script.py <<'PY'\npytest.main()\nPY",
    f"python3 -c 'import os; {_SHELL_OUT}(\"pytest tests/unit/x.py\")'",
    # Review 5 m1: importing pytest, or printing its version, runs nothing.
    'python -c "import pytest; print(pytest.__version__)"',
    "python3 -c 'import pytest' && echo importable",
    'python3 -c "import pytest, sys; print(pytest.__file__, sys.version)"',
    "python -c 'import sys, pytest; sys.exit(pytest.main(sys.argv[1:]))' tests/unit/qa",
    # Review 5 n3: the files a diff names are a targeted run.
    "pytest $(git diff --name-only main -- tests)",
    'pytest "$(git diff --name-only main -- tests)"',
    "pytest `git diff --name-only HEAD~1 -- tests`",
    "pytest $(git diff --name-only main -- tests | grep test_)",
    "git diff --name-only main -- tests | xargs pytest",
    "git diff --name-only main | grep '^tests/' | sort -u | xargs pytest",
    # Review 5 m7 sibling: a here-string is not a heredoc opener.
    "cat <<<'X'\nls\nX",
]


class TestWhatCannotBeParsed:
    """The lead's rule for review 4: what cannot be parsed denies, and says so."""

    def test_an_unparseable_command_naming_a_full_run_program_is_denied(self) -> None:
        match = find_full_qa_invocation('pytest tests/unit/x.py "unterminated', _patterns())
        assert match is not None
        assert match.fail_closed

    def test_the_deny_says_the_command_could_not_be_parsed(self) -> None:
        result = _handler().handle(_bash('pytest "unterminated'))
        assert "could not be parsed" in (result.reason or "")


#: The quoting, nesting and grammar edges of each construct the parser follows.
_EDGE_FULL_RUNS: list[str] = [
    "echo a\\ b; pytest $'tests'",
    "pytest $'tests",
    'x="$(echo \\) ; pytest tests)"',
    "x=\"$(echo ')' ; pytest tests)\"",
    'x="$( (pytest tests) )"',
    "sleep 1 & pytest tests",
    "echo -n pytest tests | bash",
    "echo pytest tests | bash -o errexit",
    "echo pytest tests | bash -s",
    "echo pytest tests | bash > log.txt",
    "flock -- /tmp/x pytest tests",
    "parallel pytest :::: files.txt",
    "hatch run pytest",
    "hatch run --verbose test:pytest tests",
    "python -mpytest tests",
    "python -X dev -m pytest tests",
    "python -u scripts/qa/llm_qa.py all",
    "bash 2>err.txt -c 'pytest tests'",
    "bash --norc -c 'pytest tests'",
    "pytest tests/{unit,{a,b}}",
    "cd a b && pytest",
    # Unsplittable code fed to a shell is judged by the unparsed check.
    "echo 'pytest tests | bash",
    'bash < <(echo "pytest tests)',
]
_EDGE_NOT_FULL_RUNS: list[str] = [
    'x="\\$(pytest tests)"',
    "echo pytest tests | bash -c 'ls'",
    "echo pytest tests | bash script.sh",
    "bash < <(cat commands.txt)",
    "source",
    "uv run --frozen",
    "uv tool run ruff check",
    "flock /tmp/x -c",
    "hatch run",
    "python",
    "python -m",
    "bash <<< 'ls'",
    "bash -c 'ls'",
    "bash script.sh",
    "pytest -- tests/unit/x.py",
    "pytest tests/unit/x.py> out.txt",
    "pytest tests/unit/{x",
    "pytest tests/unit/{x}.py",
]


class TestTheParserEdges:
    @pytest.mark.parametrize("command", _EDGE_FULL_RUNS)
    def test_a_full_run_is_found(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is not None, command

    @pytest.mark.parametrize("command", _EDGE_NOT_FULL_RUNS)
    def test_a_targeted_run_or_none_is_not(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is None, command

    def test_nesting_is_followed_to_a_fixed_depth_then_fails_closed(self) -> None:
        """Past three levels the code is not read, so naming a program denies (review 5)."""
        three_deep = find_full_qa_invocation("eval 'eval \"eval pytest\"'", _patterns())
        assert three_deep is not None
        assert not three_deep.fail_closed
        four_deep = 'eval "eval \'eval \\"eval pytest\\"\'"'
        match = find_full_qa_invocation(four_deep, _patterns())
        assert match is not None
        assert "could not be parsed" in match.fail_closed
        narrow = 'eval "eval \'eval \\"eval ls\\"\'"'
        assert find_full_qa_invocation(narrow, _patterns()) is None

    def test_a_word_no_path_can_hold_names_nothing(self, tmp_path: Path) -> None:
        """An embedded NUL cannot be looked up, so it does not target the run."""
        assert find_full_qa_invocation("pytest 'a\x00b'", _patterns(), cwd=tmp_path) is not None

    def test_an_invalid_entry_is_skipped_and_the_rest_still_apply(self) -> None:
        handler = _handler(patterns=[{"id": "broken"}, *_REPO_PATTERNS])
        assert [p.pattern_id for p in handler._patterns()] == [p["id"] for p in _REPO_PATTERNS]

    def test_targeted_forms_that_are_not_a_list_are_ignored(self) -> None:
        handler = _handler()
        handler._targeted_qa_commands = "pytest tests/unit/x.py"
        assert handler._targeted_forms() == []


#: Review 5: every former "documented limit" that ALLOWED a full run is closed
#: or fails closed. What remains is the declaration model: a program the
#: project has not declared, including a script run by its own name, is not
#: a full run. Each is named in docs/guides/HANDLER_REFERENCE.md.
_UNDECLARED_PROGRAMS: list[str] = ["tox", "nox", "./my_checks.sh", "bash my_checks.sh"]

#: Review 5 n3: the false denies the fail-closed rule accepts, also documented.
_DOCUMENTED_FALSE_DENIES: list[str] = [
    "pytest tests/unit/x.py $(cat more.txt)",
    'pytest tests/unit/x.py "$EXTRA"',
    "echo tests | xargs pytest",
]


class TestTheDocumentedLimits:
    @pytest.mark.parametrize("command", _UNDECLARED_PROGRAMS)
    def test_an_undeclared_program_is_not_a_full_run(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is None, command

    @pytest.mark.parametrize("command", _DOCUMENTED_FALSE_DENIES)
    def test_an_operand_that_cannot_be_seen_fails_closed(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is not None, command

    def test_each_limit_is_named_in_the_handler_reference(self) -> None:
        reference = (_REPO_ROOT / "docs" / "guides" / "HANDLER_REFERENCE.md").read_text(
            encoding="utf-8"
        )
        start = reference.index("#### subagent_full_qa_blocker")
        end = reference.find("\n#### ", start + 1)
        section = reference[start : end if end != -1 else len(reference)]
        for spelling in ("tox", "nox", "by its name", "$(cat more.txt)", '"$EXTRA"', "| xargs"):
            assert spelling in section, spelling


class TestPythonCodeThatRunsPytest:
    """``python -c`` code that CALLS pytest runs pytest (review 4, narrowed by review 5 m1).

    Its string literals are the run's operands, so a literal path narrows it
    and no path at all is a bare, whole-suite run. Code that only imports
    pytest, or reads its version, runs nothing.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "python -c 'import pytest; pytest.main([\"tests\"])'",
            "python3 -c 'import pytest; pytest.main()'",
            "python3.11 -c 'import pytest; raise SystemExit(pytest.main([\"-q\"]))'",
            "untracked/venv/bin/python -c 'import pytest; pytest.main([\"tests/unit\"])'",
            "uv run python -c 'import pytest; pytest.main([\".\"])'",
            "python -c 'import subprocess, sys; "
            'subprocess.run([sys.executable, "-m", "pytest", "tests"])\'',
            "python -X dev -c 'from pytest import main; main()'",
            "python3 -c'import pytest; pytest.main()'",
            "python -c \"import importlib; importlib.import_module('pytest').main(['tests'])\"",
        ],
    )
    def test_code_that_runs_the_whole_suite_is_full(self, command: str) -> None:
        match = find_full_qa_invocation(command, _patterns())
        assert match is not None, command
        assert match.pattern_id == "pytest-whole-suite"

    @pytest.mark.parametrize(
        "command",
        [
            "python -c 'import pytest; pytest.main([\"tests/unit/qa/test_x.py\"])'",
            'python3 -c \'import pytest; pytest.main(["-q", "tests/unit/handlers/"])\'',
            "python -c 'import json; print(1)'",
            "python3 -c \"print('llm_qa.py all')\"",
        ],
    )
    def test_code_that_runs_a_narrow_path_or_no_pytest_is_not(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is None, command

    def test_python_dash_m_pytest_is_still_judged(self) -> None:
        assert find_full_qa_invocation("python -m pytest", _patterns()) is not None
        assert find_full_qa_invocation("python -m pytest tests/unit/x.py", _patterns()) is None


class TestWhatCountsAsAFullRun:
    @pytest.mark.parametrize(("command", "pattern_id"), _FULL_RUNS)
    def test_a_full_run_is_found(self, command: str, pattern_id: str) -> None:
        match = find_full_qa_invocation(command, _patterns())
        assert match is not None, command
        assert match.pattern_id == pattern_id

    @pytest.mark.parametrize("command", _NOT_FULL_RUNS)
    def test_a_targeted_run_or_a_mention_is_not(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns()) is None, command

    def test_no_patterns_find_nothing(self) -> None:
        """Inert until configured: there is no built-in notion of 'full'."""
        assert find_full_qa_invocation("./scripts/qa/llm_qa.py all", []) is None


class TestThePatternShapes:
    def test_an_absent_full_args_makes_every_invocation_full(self) -> None:
        patterns, _ = parse_full_qa_patterns([{"id": "x", "command": "make-check"}])
        assert find_full_qa_invocation("make-check --fast", patterns) is not None

    def test_bare_is_not_full_unless_declared(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [{"id": "x", "command": "runner", "full_args": ["everything"]}]
        )
        assert find_full_qa_invocation("runner", patterns) is None
        assert find_full_qa_invocation("runner everything", patterns) is not None

    def test_a_read_only_flag_given_as_key_equals_value_still_counts(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [{"id": "x", "command": "runner", "read_only_flags": ["--report"]}]
        )
        assert find_full_qa_invocation("runner --report=json", patterns) is None

    def test_a_value_flag_does_not_swallow_a_key_equals_value_form(self) -> None:
        """``--ignore=path`` carries its value; the next word is still a path."""
        patterns, _ = parse_full_qa_patterns(
            [
                {
                    "id": "x",
                    "command": "pytest",
                    "full_args": ["tests"],
                    "bare_is_full": True,
                    "value_flags": ["--ignore"],
                }
            ]
        )
        assert (
            find_full_qa_invocation("pytest --ignore=tests/slow tests/unit/x.py", patterns) is None
        )


class TestOperandsArePaths:
    """Review finding 2: only a path-like word targets a run.

    A word after an undeclared flag is that flag's value far more often than a
    path, and pytest and its plugins have more value flags than any list will
    hold. So a non-flag word counts as a targeting operand only when it looks
    like a path, and anything else is ignored.
    """

    @staticmethod
    def _patterns() -> list[FullQaPattern]:
        patterns, problems = parse_full_qa_patterns(
            [{"id": "p", "command": "pytest", "full_args": ["tests"], "bare_is_full": True}]
        )
        assert not problems
        return patterns

    @pytest.mark.parametrize(
        "operand",
        ["tests/unit/test_x.py", "test_x.py", "tests/unit/test_x.py::TestA", "sub/dir"],
    )
    def test_a_path_like_word_targets_the_run(self, operand: str) -> None:
        assert find_full_qa_invocation(f"pytest {operand}", self._patterns()) is None

    @pytest.mark.parametrize("value", ["60", "DEBUG", "short", "addopts=", "8"])
    def test_a_bare_word_after_an_unknown_flag_is_its_value(self, value: str) -> None:
        match = find_full_qa_invocation(f"pytest --some-plugin-flag {value}", self._patterns())
        assert match is not None

    def test_a_word_naming_a_directory_under_cwd_targets_the_run(self, tmp_path: Path) -> None:
        (tmp_path / "handlers").mkdir()
        assert find_full_qa_invocation("pytest handlers", self._patterns(), cwd=tmp_path) is None

    def test_a_word_naming_nothing_under_cwd_does_not(self, tmp_path: Path) -> None:
        assert (
            find_full_qa_invocation("pytest handlers", self._patterns(), cwd=tmp_path) is not None
        )


class TestTheDirectoryTheCommandCdsInto:
    """Delta review N4: `cd tests/unit && pytest handlers` was judged from the event's cwd."""

    @staticmethod
    def _tree(tmp_path: Path) -> Path:
        (tmp_path / "tests" / "unit" / "handlers").mkdir(parents=True)
        return tmp_path

    def test_a_word_is_looked_up_where_the_command_cds_to(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        command = "cd tests/unit && pytest handlers"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None

    def test_each_cd_moves_on_from_the_last(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        command = "cd tests; cd unit && pytest handlers"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None

    def test_an_absolute_cd_replaces_the_directory(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        command = f"cd {root / 'tests' / 'unit'} && pytest handlers"
        assert find_full_qa_invocation(command, _patterns(), cwd=Path("/elsewhere")) is None

    def test_a_word_absent_where_the_command_cds_to_is_still_full(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        command = "cd tests/unit && pytest nothing_here"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "cd tests && pytest unit",
            "cd tests/unit && pytest ../unit",
            "cd tests/unit && pytest ..",
            "cd tests/unit/handlers && pytest ../../../tests",
            "cd tests/unit && pytest ../..",
            "cd tests/unit && pytest ../../..",
            "pytest ..",
        ],
    )
    def test_an_operand_is_judged_where_it_resolves_from_the_start(
        self, tmp_path: Path, command: str
    ) -> None:
        """Review 3 R7: the cd moved only the existence lookup, not the full-suite check.

        An operand reaching the whole start directory, or above it, runs the
        whole suite too.
        """
        root = self._tree(tmp_path)
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is not None, command

    @pytest.mark.parametrize(
        "command",
        ["cd tests/unit && pytest handlers", "cd tests && pytest unit/handlers"],
    )
    def test_a_narrower_operand_from_a_cd_stays_targeted(
        self, tmp_path: Path, command: str
    ) -> None:
        root = self._tree(tmp_path)
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None, command

    @pytest.mark.parametrize("dot", [".", "./"])
    def test_the_current_directory_after_a_cd_is_where_the_cd_went(
        self, tmp_path: Path, dot: str
    ) -> None:
        """Review 4 N8: `.` was matched literally against `full_args` before resolving."""
        root = self._tree(tmp_path)
        command = f"cd tests/unit/handlers && pytest {dot}"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None
        assert find_full_qa_invocation(f"cd tests/unit && pytest {dot}", _patterns(), cwd=root)

    @pytest.mark.parametrize("bare", ["pytest", "pytest -q", "pytest -x -p no:randomly"])
    def test_a_bare_run_collects_where_the_cd_went(self, tmp_path: Path, bare: str) -> None:
        """Review 4 probe: `cd tests/unit/qa && pytest -q` was denied as bare, hence full.

        From below the repository root pytest collects the directory it runs
        in, so a bare run is judged as the operand ``.`` from there.
        """
        root = self._tree(tmp_path)
        (root / "pyproject.toml").write_text("", encoding="utf-8")
        assert (
            find_full_qa_invocation(f"cd tests/unit/handlers && {bare}", _patterns(), cwd=root)
            is None
        )
        for full in ("cd tests/unit", "cd tests", "cd tests/unit/handlers/../..", "cd $X"):
            assert find_full_qa_invocation(f"{full} && {bare}", _patterns(), cwd=root), full

    def test_a_cd_it_cannot_resolve_falls_back_to_the_path_shape(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path)
        assert find_full_qa_invocation("cd $X && pytest handlers", _patterns(), cwd=root)
        assert find_full_qa_invocation("cd $X && pytest a/b.py", _patterns(), cwd=root) is None


class TestOperandsAreJudgedFromTheirRepository:
    """Review 4 N6: `full_args` were placed relative to the event's cwd.

    A teammate starts in the main checkout and names a worktree's suite by
    path, so the suite is judged against the repository that CONTAINS the
    operand: the nearest directory holding ``.git`` or ``pyproject.toml``.
    """

    @staticmethod
    def _checkout(tmp_path: Path) -> Path:
        repo = tmp_path / "untracked" / "worktrees" / "wt"
        (repo / "tests" / "unit" / "handlers").mkdir(parents=True)
        (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        return repo

    @pytest.mark.parametrize(
        "command",
        [
            "pytest untracked/worktrees/wt/tests",
            "pytest untracked/worktrees/wt/tests/unit",
            "pytest untracked/worktrees/wt",
            "cd untracked/worktrees/wt/tests/unit/handlers && pytest ../..",
        ],
    )
    def test_a_suite_named_from_outside_its_repository_is_full(
        self, tmp_path: Path, command: str
    ) -> None:
        self._checkout(tmp_path)
        assert find_full_qa_invocation(command, _patterns(), cwd=tmp_path) is not None, command

    def test_the_repository_root_by_absolute_path_is_full(self, tmp_path: Path) -> None:
        repo = self._checkout(tmp_path)
        assert find_full_qa_invocation(f"pytest {repo}", _patterns(), cwd=tmp_path) is not None

    def test_from_inside_the_tests_directory_a_whole_subtree_is_full(self, tmp_path: Path) -> None:
        repo = self._checkout(tmp_path)
        assert find_full_qa_invocation("pytest unit", _patterns(), cwd=repo / "tests") is not None

    def test_a_narrow_path_into_another_repository_stays_targeted(self, tmp_path: Path) -> None:
        self._checkout(tmp_path)
        command = "pytest untracked/worktrees/wt/tests/unit/handlers"
        assert find_full_qa_invocation(command, _patterns(), cwd=tmp_path) is None


class TestSubcommandWordsAfterACd:
    """Review 5 M1: `all` and `tests` were resolved as PATHS below the repository root.

    ``llm_qa.py`` finds its project from its own location, so ``all`` runs the
    whole suite wherever the command stands. A ``full_args`` entry that is a
    plain word (no ``/``, not ``.``) and names nothing in the directory the
    command runs in is matched literally, before any path resolution.
    """

    @staticmethod
    def _repo(tmp_path: Path) -> Path:
        for directory in ("scripts/qa", "CLAUDE", "tests/unit", "docs"):
            (tmp_path / directory).mkdir(parents=True)
        (tmp_path / ".git").mkdir()
        (tmp_path / "scripts" / "qa" / "llm_qa.py").write_text("", encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize(
        ("command", "start"),
        [
            ("cd scripts/qa && ./llm_qa.py all", "."),
            ("cd scripts && qa/llm_qa.py all", "."),
            ("cd CLAUDE && ../scripts/qa/llm_qa.py all", "."),
            ("cd tests && ../scripts/qa/llm_qa.py tests", "."),
            ("cd docs && python3 ../scripts/qa/llm_qa.py all", "."),
            ("./llm_qa.py all", "scripts/qa"),
            ("../scripts/qa/llm_qa.py all", "CLAUDE"),
            ("cd scripts/qa && ./run_all.sh", "."),
            ("./scripts/qa/llm_qa.py all", "."),
        ],
    )
    def test_a_subcommand_word_is_full_wherever_the_command_stands(
        self, tmp_path: Path, command: str, start: str
    ) -> None:
        root = self._repo(tmp_path)
        assert find_full_qa_invocation(command, _patterns(), cwd=root / start), command

    def test_a_read_only_run_after_a_cd_is_still_allowed(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path)
        command = "cd tests && ../scripts/qa/llm_qa.py all --read-only"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None

    def test_a_word_naming_a_directory_where_the_command_stands_is_a_path(
        self, tmp_path: Path
    ) -> None:
        """``cd tests && pytest unit/x`` stays targeted; the literal match needs no such path."""
        root = self._repo(tmp_path)
        (root / "tests" / "unit" / "tests").mkdir()
        command = "cd tests/unit && pytest tests"
        assert find_full_qa_invocation(command, _patterns(), cwd=root) is None


class TestBraceExpansionIsBounded:
    """Review 5 M2: the expansion was built in full before the cap, so the work was 2^n.

    A 139-character command with 23 groups took 18 s; past the client's 30 s
    budget the whole PreToolUse chain fails open. The work is now bounded by
    the cap, and a word with more alternatives than the cap is judged as the
    whole suite: it cannot be judged, so it fails closed.
    """

    _BUDGET_SECONDS = 1.0

    @pytest.mark.parametrize("groups", [24, 40, 200])
    def test_many_groups_are_judged_within_a_second(self, groups: int) -> None:
        command = "pytest " + "{a,b}" * groups + " --co; git status"
        began = time.perf_counter()
        find_full_qa_invocation(command, _patterns())
        assert time.perf_counter() - began < self._BUDGET_SECONDS

    @pytest.mark.parametrize("groups", [7, 24])
    def test_more_alternatives_than_the_cap_fail_closed(self, groups: int) -> None:
        command = "pytest tests/unit/qa/test_" + "{a,b}" * groups + ".py"
        assert find_full_qa_invocation(command, _patterns()) is not None

    def test_alternatives_within_the_cap_are_judged_one_by_one(self) -> None:
        command = "pytest tests/unit/qa/test_" + "{a,b}" * 5 + ".py"
        assert find_full_qa_invocation(command, _patterns()) is None

    def test_deeply_nested_braces_fail_closed_without_recursing(self) -> None:
        command = "pytest tests/unit/qa/" + "{a," * 2000 + "b" + "}" * 2000
        assert find_full_qa_invocation(command, _patterns()) is not None


class TestEnvChdirIsACdForOneCommand:
    """Review 5 n3: ``env -C DIR cmd`` runs ``cmd`` in DIR, and nothing after it."""

    @pytest.mark.parametrize(
        "command", ["env -C tests/unit/qa pytest", "env --chdir=tests/unit/qa pytest -q"]
    )
    def test_a_bare_run_in_a_narrow_directory_is_targeted(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns(), cwd=_REPO_ROOT) is None

    @pytest.mark.parametrize(
        "command",
        [
            "env -C tests pytest",
            "env -C tests/unit/qa pytest && pytest",
            "env --chdir=tests/unit/qa pytest; pytest",
            "env -C tests/unit/qa true; ./scripts/qa/llm_qa.py all",
        ],
    )
    def test_the_directory_does_not_outlive_the_command(self, command: str) -> None:
        assert find_full_qa_invocation(command, _patterns(), cwd=_REPO_ROOT), command


class TestCodeAShellReadsFromAFile:
    """Review 5: ``cat f | bash`` and ``bash < f`` were a documented limit.

    The file is read, when it is a regular file of a bounded size, and its
    lines are judged as the shell will run them. A file that cannot be read is
    judged by its NAME, as ``bash f`` is, so a declared script still matches.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "cat commands.txt | bash",
            "bash < commands.txt",
            "sh <commands.txt",
            "cat ./commands.txt | sh -s",
            "python3 < code.py",
            "cat code.py | python3 -",
        ],
    )
    def test_a_file_that_runs_the_suite_is_full(self, tmp_path: Path, command: str) -> None:
        (tmp_path / "commands.txt").write_text("echo start\npytest tests\n", encoding="utf-8")
        (tmp_path / "code.py").write_text("import pytest\npytest.main([])\n", encoding="utf-8")
        assert find_full_qa_invocation(command, _patterns(), cwd=tmp_path), command

    @pytest.mark.parametrize(
        "command", ["cat commands.txt | bash", "bash < commands.txt", "python3 < code.py"]
    )
    def test_a_file_that_runs_a_narrow_path_is_not(self, tmp_path: Path, command: str) -> None:
        (tmp_path / "commands.txt").write_text("pytest tests/unit/x.py\n", encoding="utf-8")
        (tmp_path / "code.py").write_text("print('pytest')\n", encoding="utf-8")
        assert find_full_qa_invocation(command, _patterns(), cwd=tmp_path) is None, command

    def test_a_missing_file_is_judged_by_its_name(self, tmp_path: Path) -> None:
        assert find_full_qa_invocation("cat absent.txt | bash", _patterns(), cwd=tmp_path) is None
        assert find_full_qa_invocation(
            "cat scripts/qa/run_all.sh | bash", _patterns(), cwd=tmp_path
        )

    def test_a_file_past_the_size_cap_is_judged_by_its_name(self, tmp_path: Path) -> None:
        big = "echo pad\n" * 20_000 + "pytest tests\n"
        (tmp_path / "big.txt").write_text(big, encoding="utf-8")
        assert find_full_qa_invocation("bash < big.txt", _patterns(), cwd=tmp_path) is None

    def test_a_cd_inside_the_file_stays_inside_it(self, tmp_path: Path) -> None:
        (tmp_path / "tests" / "unit" / "qa").mkdir(parents=True)
        (tmp_path / ".git").mkdir()
        (tmp_path / "commands.txt").write_text("cd tests/unit/qa\n", encoding="utf-8")
        command = "bash < commands.txt; pytest"
        assert find_full_qa_invocation(command, _patterns(), cwd=tmp_path)


class TestWhatCannotBeSeenFailsClosed:
    """Review 5: a construct whose run cannot be seen is denied when it may be the suite.

    The deny says which construct it was, so a sub-agent can spell the run
    out plainly instead.
    """

    def test_a_dynamic_import_that_calls_main_is_denied_as_opaque(self) -> None:
        command = f"python -c \"{_DUNDER_IMPORT}('py'+'test').main()\""
        match = find_full_qa_invocation(command, _patterns())
        assert match is not None
        assert match.pattern_id == "pytest-whole-suite"
        assert "run time" in match.fail_closed

    def test_a_dynamic_import_with_a_narrow_path_is_not(self) -> None:
        command = f"python -c \"{_DUNDER_IMPORT}('py'+'test').main(['tests/unit/x.py'])\""
        assert find_full_qa_invocation(command, _patterns()) is None

    def test_a_program_named_by_a_substitution_says_so(self) -> None:
        match = find_full_qa_invocation("$(which pytest) tests", _patterns())
        assert match is not None
        assert "run time" in match.fail_closed

    def test_the_deny_carries_the_reason(self) -> None:
        result = _handler().handle(_bash("$(which pytest) tests"))
        assert "run time" in (result.reason or "")

    def test_an_unparsed_command_says_it_could_not_be_parsed(self) -> None:
        match = find_full_qa_invocation('pytest "unterminated', _patterns())
        assert match is not None
        assert "could not be parsed" in match.fail_closed


class TestTheWorkIsBounded:
    """Review 5 n5 and n6: a long command, or deep nesting, fails closed quickly."""

    _BUDGET_SECONDS = 1.0

    def test_a_command_past_the_size_cap_naming_a_program_is_denied(self) -> None:
        command = "echo " + "a" * 400_000 + "; pytest tests/unit/x.py"
        began = time.perf_counter()
        match = find_full_qa_invocation(command, _patterns())
        assert time.perf_counter() - began < self._BUDGET_SECONDS
        assert match is not None
        assert "too long" in match.fail_closed

    def test_a_command_past_the_size_cap_naming_no_program_is_allowed(self) -> None:
        assert find_full_qa_invocation("echo " + "a" * 400_000, _patterns()) is None

    def test_a_long_prose_heredoc_within_the_cap_is_parsed(self) -> None:
        prose = "Run pytest tests before merging.\n" * 600
        command = f"cat > notes.md <<'EOF'\n{prose}EOF"
        assert find_full_qa_invocation(command, _patterns()) is None

    @pytest.mark.parametrize("launcher", ["setsid ", "uv run ", "xargs ", "python -m "])
    def test_deep_launcher_nesting_fails_closed_without_recursion_error(
        self, launcher: str
    ) -> None:
        match = find_full_qa_invocation(launcher * 1000 + "pytest tests/unit/x.py", _patterns())
        assert match is not None
        assert "could not be parsed" in match.fail_closed

    def test_shallow_launcher_nesting_is_still_followed(self) -> None:
        command = "setsid " * 10 + "pytest tests/unit/x.py"
        assert find_full_qa_invocation(command, _patterns()) is None
        assert find_full_qa_invocation("setsid " * 10 + "pytest", _patterns())


class TestARunnerTheProjectDeclares:
    """Review 5: ``tox`` and ``nox`` run whatever the project configures.

    What they run is the project's to declare, as ``llm_qa.py`` is here: a
    pattern naming the runner denies it.
    """

    def test_a_declared_runner_is_denied(self) -> None:
        patterns, problems = parse_full_qa_patterns(
            [{"id": "tox", "command": "tox"}, {"id": "nox", "command": "nox"}]
        )
        assert not problems
        for command in ("tox", "tox -e py311", "uv run tox", "nox -s tests"):
            assert find_full_qa_invocation(command, patterns), command


class TestAnUnknownFlagUnderAGrammar:
    """Delta review N4: a plugin flag the grammar does not know used to fail open.

    Under ``option_grammar`` every option pytest has is known, so an unknown
    one is a plugin's, and it is read as taking a value (fail closed). Name the
    test paths first, or pass the value as ``--flag=value``.
    """

    def test_its_next_word_is_its_value_even_when_path_shaped(self) -> None:
        match = find_full_qa_invocation("pytest --plugin-flag tests/unit/x.py", _patterns())
        assert match is not None

    def test_without_a_grammar_an_undeclared_flag_takes_no_value(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [{"id": "x", "command": "runner", "full_args": ["all"], "bare_is_full": True}]
        )
        assert find_full_qa_invocation("runner --flag tests/unit/x.py", patterns) is None

    def test_every_boolean_option_of_the_running_pytest_is_known(
        self, pytestconfig: pytest.Config
    ) -> None:
        """The other half of the grammar pin: without it, a boolean reads as unknown."""
        parser = pytestconfig._parser.optparser
        takes_none = {
            option
            for action in parser._actions
            if action.nargs == 0
            for option in action.option_strings
        }
        assert takes_none, "the parser exposed no options; this test would prove nothing"
        assert takes_none <= PYTEST_FLAG_OPTIONS, sorted(takes_none - PYTEST_FLAG_OPTIONS)


class TestThePytestOptionGrammar:
    """``option_grammar: pytest`` brings pytest's real value-taking options."""

    def test_every_value_option_of_the_running_pytest_is_known(
        self, pytestconfig: pytest.Config
    ) -> None:
        """Pinned to the parser of THIS pytest and its installed plugins.

        ``optparser`` is pytest's private argparse parser. It is read here
        because it is the grammar itself: a hand-kept list checked against
        nothing is how the holes in review finding 2 came about.
        """
        parser = pytestconfig._parser.optparser
        takes_value = {
            option
            for action in parser._actions
            if action.nargs != 0
            for option in action.option_strings
        }
        assert takes_value, "the parser exposed no options; this test would prove nothing"
        assert takes_value <= PYTEST_VALUE_OPTIONS, sorted(takes_value - PYTEST_VALUE_OPTIONS)

    def test_the_grammar_consumes_a_value_that_looks_like_a_path(self) -> None:
        patterns, _ = parse_full_qa_patterns(
            [
                {
                    "id": "p",
                    "command": "pytest",
                    "full_args": ["tests"],
                    "bare_is_full": True,
                    "option_grammar": "pytest",
                }
            ]
        )
        assert find_full_qa_invocation("pytest --basetemp /tmp/x", patterns) is not None

    def test_an_unknown_grammar_is_reported(self) -> None:
        patterns, problems = parse_full_qa_patterns(
            [{"id": "p", "command": "pytest", "option_grammar": "nose"}]
        )
        assert patterns == []
        assert any("option_grammar" in problem for problem in problems)


class TestConfigParsing:
    def test_the_repo_patterns_parse_cleanly(self) -> None:
        patterns, problems = parse_full_qa_patterns(_REPO_PATTERNS)
        assert problems == []
        assert [p.pattern_id for p in patterns] == [p["id"] for p in _REPO_PATTERNS]

    @pytest.mark.parametrize(
        "entry",
        [
            {"command": "pytest"},
            {"id": "x"},
            {"id": "", "command": "pytest"},
            {"id": "x", "command": "pytest", "full_args": "tests"},
            {"id": "x", "command": "pytest", "bare_is_full": "yes"},
            {"id": "x", "command": "pytest", "surprise": True},
            "pytest",
        ],
    )
    def test_a_malformed_entry_is_reported_and_skipped(self, entry: Any) -> None:
        valid = {"id": "ok", "command": "run_all.sh"}
        patterns, problems = parse_full_qa_patterns([entry, valid])
        assert [p.pattern_id for p in patterns] == ["ok"]
        assert len(problems) == 1

    def test_a_non_list_is_reported(self) -> None:
        patterns, problems = parse_full_qa_patterns({"id": "x", "command": "pytest"})
        assert patterns == []
        assert problems

    def test_none_is_an_empty_declaration(self) -> None:
        assert parse_full_qa_patterns(None) == ([], [])

    def test_duplicate_ids_are_reported(self) -> None:
        entry = {"id": "x", "command": "pytest"}
        patterns, problems = parse_full_qa_patterns([entry, dict(entry)])
        assert len(patterns) == 1
        assert problems


# ── The handler ────────────────────────────────────────────────────────────


class TestTheScopeCarriesTheRoleTest:
    """Main thread vs sub-agent is decided by the chain, never re-derived here."""

    def test_the_handler_is_scoped_to_sub(self) -> None:
        assert SubagentFullQaBlockerHandler().scope is HandlerScope.SUB

    @pytest.mark.parametrize(
        "agent_id",
        [
            pytest.param("a1b2c3d4e5f6a7b8c", id="agent-tool-17-chars"),
            pytest.param("aplan463-impl-84165102c3e9edf0", id="in-process-teammate-30-chars"),
            pytest.param("w", id="unmeasured-kind-any-non-empty-id"),
        ],
    )
    def test_a_subagent_event_is_admitted_whatever_the_ids_shape(self, agent_id: str) -> None:
        """Both measured kinds, plus one no one has measured (a Workflow-tool agent).

        Admission keys on a non-empty ``agent_id`` alone, so a kind that turns
        out to carry the field is covered with no change here.
        """
        event = _bash("./scripts/qa/llm_qa.py all", agent_id=agent_id)
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is True

    def test_an_empty_agent_id_is_not_a_subagent(self) -> None:
        event = _bash("./scripts/qa/llm_qa.py all", agent_id="")
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is False

    def test_a_main_thread_event_is_not_admitted(self) -> None:
        """The coordinator's full gate must draw nothing at all."""
        event = _bash("./scripts/qa/llm_qa.py all")
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is False

    def test_a_synthetic_event_is_not_admitted_even_with_an_agent_id(self) -> None:
        event = _bash(
            "./scripts/qa/llm_qa.py all",
            agent_id="a-probe",
            **{SYNTHETIC_SOURCE_FIELD: PLAYBOOK_PROBE},
        )
        assert scope_admits(SubagentFullQaBlockerHandler().scope, event) is False

    def test_the_handler_does_not_read_agent_id_itself(self) -> None:
        """No agent_id in the payload, and it still matches: admission is not its job."""
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py all")) is True


class TestWhatTheHandlerMatches:
    def test_a_full_run_matches(self) -> None:
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py all")) is True

    def test_a_targeted_run_does_not_match(self) -> None:
        assert _handler().matches(_bash("./scripts/qa/llm_qa.py lint type_check")) is False

    def test_a_non_bash_tool_does_not_match(self) -> None:
        event = {"tool_name": "Write", "tool_input": {"content": "./scripts/qa/llm_qa.py all"}}
        assert _handler().matches(event) is False

    def test_an_empty_command_does_not_match(self) -> None:
        assert _handler().matches(_bash("")) is False

    def test_an_unconfigured_handler_matches_nothing(self) -> None:
        assert _handler(patterns=[]).matches(_bash("./scripts/qa/llm_qa.py all")) is False

    def test_the_events_cwd_decides_whether_a_bare_word_is_a_path(self, tmp_path: Path) -> None:
        (tmp_path / "handlers").mkdir()
        assert _handler().matches(_bash("pytest handlers", cwd=str(tmp_path))) is False
        assert _handler().matches(_bash("pytest nothing_here", cwd=str(tmp_path))) is True

    def test_a_config_change_after_first_use_is_honoured(self) -> None:
        """Options arrive by setattr after construction; parsing must not freeze the first view."""
        handler = _handler(patterns=[])
        assert handler.matches(_bash("./scripts/qa/run_all.sh")) is False
        handler._full_qa_patterns = _REPO_PATTERNS
        assert handler.matches(_bash("./scripts/qa/run_all.sh")) is True


class TestTheDenial:
    def _reason(self, command: str, targeted: list[str] | None = None) -> str:
        result = _handler(targeted=targeted).handle(_bash(command))
        assert result.decision is Decision.DENY
        return result.reason or ""

    def test_it_denies_with_the_rule_id(self) -> None:
        assert RuleID.SUBAGENT_FULL_QA in self._reason("./scripts/qa/llm_qa.py all")

    def test_the_reason_says_the_coordinator_runs_the_full_gate(self) -> None:
        assert "coordinator" in self._reason("./scripts/qa/llm_qa.py all").lower()

    @pytest.mark.parametrize("surface", ["reason", "guidance"])
    def test_it_describes_the_batched_gate_not_one_run_per_branch(self, surface: str) -> None:
        """Owner's instruction: one full run over every ready branch merged together.

        A deny or resident guidance that still said "once per delivery, one run
        at a time" would teach the per-branch queue the owner ruled out.
        """
        handler = _handler()
        text = (
            self._reason("./scripts/qa/llm_qa.py all")
            if surface == "reason"
            else handler.get_claude_md() or ""
        )
        assert "every ready branch" in text
        assert "once per delivery" not in text
        assert "one run at a time" not in text

    def test_the_reason_names_every_configured_targeted_form(self) -> None:
        reason = self._reason("./scripts/qa/llm_qa.py all")
        for command in _TARGETED:
            assert command in reason

    def test_the_reason_names_the_pattern_that_matched(self) -> None:
        assert "pytest-whole-suite" in self._reason("pytest tests/")

    def test_without_declared_targeted_forms_it_still_names_a_way_forward(self) -> None:
        reason = self._reason("./scripts/qa/llm_qa.py all", targeted=[])
        assert "explicit" in reason.lower()

    def test_handle_on_a_command_it_does_not_match_allows(self) -> None:
        """handle() re-derives the match rather than trusting a stale matches() call."""
        result = _handler().handle(_bash("./scripts/qa/llm_qa.py lint"))
        assert result.decision is Decision.ALLOW

    def test_get_rules_declares_the_rule(self) -> None:
        assert [rule.rule_id for rule in _handler().get_rules()] == [RuleID.SUBAGENT_FULL_QA]


class TestDefaultsAndPosture:
    def test_off_by_default(self) -> None:
        """A client's full-QA commands cannot be known from here, so it ships opt-in."""
        assert SubagentFullQaBlockerHandler().get_default_enabled() is False

    def test_an_empty_declaration_is_reported_not_silent(self, tmp_path: Any) -> None:
        status = _handler(patterns=[]).get_enforcement_status(tmp_path)
        assert status
        assert "full_qa_patterns" in status[0]

    def test_a_malformed_entry_is_reported(self, tmp_path: Any) -> None:
        handler = _handler(patterns=[{"id": "x"}, *_REPO_PATTERNS])
        status = handler.get_enforcement_status(tmp_path)
        assert any("command" in line for line in status)

    def test_a_clean_declaration_reports_nothing(self, tmp_path: Any) -> None:
        assert _handler().get_enforcement_status(tmp_path) == []

    @pytest.mark.parametrize("scope", [HandlerScope.ALL, HandlerScope.MAIN])
    def test_a_scope_other_than_sub_is_reported(self, tmp_path: Any, scope: HandlerScope) -> None:
        """Review finding 7: `scope: ALL` from config denies the coordinator's own gate."""
        handler = _handler()
        handler.scope = scope
        status = handler.get_enforcement_status(tmp_path)
        assert any("scope" in line and "SUB" in line for line in status), status


class TestTheAcceptanceTestsRunInASubagentContext:
    """The live harness marks every probe synthetic, and a SUB-scoped handler
    declines a synthetic event by construction. So the probes are declared as
    raw ``hook_input`` carrying an ``agent_id``: the in-process contract test
    drives the configured handler with them, and the live harness skips them
    rather than observing a vacuous ALLOW."""

    def test_there_is_a_deny_and_a_near_miss_allow(self) -> None:
        decisions = {t.expected_decision for t in _handler().get_acceptance_tests()}
        assert decisions == {Decision.DENY, Decision.ALLOW}

    def test_every_probe_is_a_subagent_payload(self) -> None:
        for test in _handler().get_acceptance_tests():
            assert test.hook_input is not None, test.title
            assert test.hook_input.get("agent_id"), test.title
