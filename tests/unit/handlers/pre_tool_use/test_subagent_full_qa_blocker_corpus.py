"""The review 8 corpus for `subagent_full_qa_blocker`, kept as a permanent test (Plan 00463).

Review 8 judged the guard against two corpora and found it wrong in both
directions. They are kept here so neither can regress unseen:

1. **Missed full runs.** Commands that run the whole suite through a Python
   script, a shell file, a substitution, a launcher, a ``find -exec`` or a
   ``git diff`` listing, beside near neighbours that run something narrower.
   Each row carries the verdict it must get.
2. **Everyday commands.** What a sub-agent routinely runs in this repository:
   targeted pytest, the named ``llm_qa.py`` tools, the static tools, git, gh,
   reading and grepping, and every ``scripts/qa`` script except the two that
   are the full suite by design. None of them may be denied.

The commands are judged with the live declaration from this repository's
config, in this repository's root, so a ``tests`` operand is the real suite
directory. The fixture files are written under a temporary directory; the
Python ones are data in ``tests/fixtures/subagent_full_qa_corpus``.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    FullQaPattern,
    SubagentFullQaBlockerHandler,
    find_full_qa_invocation,
    parse_full_qa_patterns,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYTHON_SOURCES = (
    _REPO_ROOT / "tests" / "fixtures" / "subagent_full_qa_corpus" / "python_sources.json"
)
#: Replaced by the fixture directory in each command.
_FX = "@FX@"
#: The Python fixtures that run something narrower than the suite, or nothing.
_PYTHON_NOT_FULL: frozenset[str] = frozenset({"ctl_tgt.py", "ctl_doc.py", "ctl_log.py"})
_SHELL_SOURCES: dict[str, str] = {
    # PYTEST_ADDOPTS set by a SOURCED file after the first judgement.
    "x_tgt.sh": "pytest tests/unit/qa\n",
    "y_addopts.sh": "export PYTEST_ADDOPTS=tests\n",
    # A verdict computed near the nesting limit, reused at the top.
    "p.sh": f"bash {_FX}/q.sh\n",
    "q.sh": f"bash {_FX}/x.sh\n",
    "x.sh": f"bash {_FX}/yy.sh\n",
    "yy.sh": f"bash {_FX}/z.sh\n",
    "z.sh": "pytest tests\n",
    # Files that run each other.
    "cyc_a.sh": f"bash {_FX}/cyc_b.sh\n",
    "cyc_b.sh": f"bash {_FX}/cyc_a.sh\npytest tests\n",
    "arg1.sh": 'pytest "$1"\n',
    "full.sh": "pytest tests\n",
    "tgt.sh": "pytest tests/unit/qa\n",
    # A file named like a program that only sets up the environment.
    "ssh-agent": "#!/bin/sh\necho 'pytest tests'\n",
}

_FULL = True
_NOT_FULL = False
_LISTED_ROWS: list[tuple[str, bool]] = [
    (f"bash {_FX}/x_tgt.sh; source {_FX}/y_addopts.sh; bash {_FX}/x_tgt.sh", _FULL),
    (f"source {_FX}/y_addopts.sh; bash {_FX}/x_tgt.sh", _FULL),
    (f"bash {_FX}/x_tgt.sh; . {_FX}/y_addopts.sh && bash {_FX}/x_tgt.sh", _FULL),
    (f"bash {_FX}/p.sh; bash {_FX}/x.sh", _FULL),
    (f"bash {_FX}/x.sh", _FULL),
    (f"bash {_FX}/p.sh", _FULL),
    (f"bash {_FX}/cyc_a.sh", _FULL),
    (f"bash {_FX}/cyc_b.sh", _FULL),
    (f"bash {_FX}/cyc_a.sh; bash {_FX}/cyc_b.sh", _FULL),
    (f"bash -s -- tests < {_FX}/arg1.sh", _FULL),
    (f"cat {_FX}/arg1.sh | bash -s -- tests", _FULL),
    (f"bash -s tests < {_FX}/arg1.sh", _FULL),
    (f"bash -xs -- tests < {_FX}/arg1.sh", _FULL),
    (f"bash -s -- tests/unit/qa < {_FX}/arg1.sh", _NOT_FULL),
    ("bash -c 'pytest \"$1\"' _ tests", _FULL),
    ("sh -c 'pytest \"$0\"' tests", _FULL),
    (f'bash -c "$(cat {_FX}/arg1.sh)" _ tests', _FULL),
    (f'python3 -c "$(cat {_FX}/ctl_in_call.py)"', _FULL),
    (f'bash <<< "$(cat {_FX}/full.sh)"', _FULL),
    (f"$(cat {_FX}/full.sh)", _FULL),
    (f"`cat {_FX}/full.sh`", _FULL),
    (f'bash -c "x=1; $(cat {_FX}/full.sh)"', _FULL),
    (f"F={_FX}/full.sh; cat $F | bash", _FULL),
    (f"F={_FX}/full.sh; bash < $F", _FULL),
    (f'F={_FX}/full.sh; bash <<< "$(cat $F)"', _FULL),
    ('cat "$SCRIPT" | bash', _FULL),
    ('bash "$SCRIPT"', _FULL),
    (f"F={_FX}/tgt.sh; cat $F | bash", _NOT_FULL),
    ("eval \"$(ssh-agent bash -c 'pytest tests')\"", _FULL),
    ("ssh-agent bash -c 'pytest tests'", _FULL),
    ("ssh-agent pytest tests", _FULL),
    ('eval "$(pyenv init -)"; pytest tests', _FULL),
    ('eval "$(pyenv init -)" && ./scripts/qa/llm_qa.py all', _FULL),
    ("pyenv exec pytest tests", _FULL),
    ("source <(pyenv exec python -c 'print(\"pytest tests\")')", _FULL),
    ("source <(conda run python -c 'print(\"pytest tests\")')", _FULL),
    (f"source <(brew cat {_FX}/full.sh)", _FULL),
    (f"bash <(direnv exec . cat {_FX}/full.sh)", _FULL),
    (f"cat {_FX}/full.sh | direnv exec . bash", _FULL),
    (f"direnv exec . cat {_FX}/full.sh | bash", _FULL),
    (f"pyenv exec cat {_FX}/full.sh | bash", _FULL),
    (f"rbenv exec cat {_FX}/full.sh | bash", _FULL),
    (f"conda run cat {_FX}/full.sh | bash", _FULL),
    (f'eval "$(pyenv exec cat {_FX}/full.sh)"', _FULL),
    (f'eval "$(cat {_FX}/full.sh completion)"', _FULL),
    (f"source <(cat {_FX}/full.sh completion bash)", _FULL),
    (f'eval "$(awk 1 {_FX}/full.sh completion)"', _FULL),
    (f'eval "$({_FX}/ssh-agent)"', _FULL),
    (f'cd {_FX} && eval "$(./ssh-agent -s)"', _FULL),
    ('eval "$(ssh-agent -s)" && ssh-add -l', _NOT_FULL),
    ("source <(kubectl completion bash)", _NOT_FULL),
    ('eval "$(direnv export bash)"', _NOT_FULL),
    (
        'git diff --name-only "$(git merge-base main HEAD)" -- tests | xargs -r pytest',
        _NOT_FULL,
    ),
    (
        'git diff --name-only "$(git merge-base --fork-point main)" -- tests | xargs -r pytest',
        _FULL,
    ),
    (
        'git diff --name-only "$(git merge-base main HEAD; echo '
        '4b825dc642cb6eb9a060e54bf8d69288fbee4904)" -- tests | xargs -r pytest',
        _FULL,
    ),
    (
        'git diff --name-only "$(git merge-base main HEAD && echo --format=%s)" '
        "| xargs -r pytest",
        _FULL,
    ),
    (
        "git diff --name-only $(git merge-base --octopus HEAD) -- tests | xargs -r pytest",
        _FULL,
    ),
    (
        'git diff --name-only "$(git merge-base -a main HEAD)" -- tests | xargs -r pytest',
        _FULL,
    ),
    (
        "git diff --name-only $(git merge-base main HEAD) $(git merge-base HEAD main) "
        "-- tests | xargs -r pytest",
        _NOT_FULL,
    ),
    ("find tests -name 'test_*.py' -exec pytest {} +", _FULL),
    ("find tests -maxdepth 0 -exec pytest {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec pytest {}/ \\;", _FULL),
    ("find tests -maxdepth 0 -exec pytest ./{} \\;", _FULL),
    ("find tests -maxdepth 0 -exec pytest {}/unit/.. \\;", _FULL),
    ("find tests -prune -exec pytest {} +", _FULL),
    ("find tests -maxdepth 0 -exec sh -c 'pytest \"$1\"' _ {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec bash -c 'pytest \"$@\"' _ {} +", _FULL),
    ("find tests -maxdepth 0 -exec env pytest {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec python3 -m pytest {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec ./scripts/qa/llm_qa.py {} \\;", _FULL),
    ("find tests -maxdepth 0 -type d -exec pytest {} \\;", _FULL),
    ("find -L tests -maxdepth 0 -exec pytest {} \\;", _FULL),
    ("find . -maxdepth 1 -name tests -exec pytest {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec echo {} \\; -exec pytest {} \\;", _FULL),
    ("find tests -maxdepth 0 -exec pytest {} ';'", _FULL),
    ("find tests -maxdepth 0 -exec pytest '{}' \\;", _FULL),
    ("find tests/unit/qa -maxdepth 0 -exec pytest {}/../.. \\;", _FULL),
    ("find tests/unit/qa -exec pytest {} +", _NOT_FULL),
    ("find tests/unit/qa -name 'test_*.py' -exec pytest {} +", _NOT_FULL),
    ("find tests -name '*.pyc' -delete", _NOT_FULL),
    ("find tests -name '*.py' -exec grep -l pytest {} +", _NOT_FULL),
    ("find . -name '*.py' -exec ruff check {} +", _NOT_FULL),
    ("find src -name '*.py' -exec wc -l {} +", _NOT_FULL),
]


def _python_sources() -> dict[str, str]:
    sources = json.loads(_PYTHON_SOURCES.read_text(encoding="utf-8"))
    assert isinstance(sources, dict)
    return {str(name): str(text) for name, text in sources.items()}


def _corpus_rows() -> list[tuple[str, bool]]:
    python_rows = [
        (f"python3 {_FX}/{name}", name not in _PYTHON_NOT_FULL) for name in _python_sources()
    ]
    return [*python_rows, *_LISTED_ROWS]


#: The two ``scripts/qa`` entry points that ARE the full suite.
_FULL_BY_DESIGN: frozenset[str] = frozenset({"run_all.sh", "run_tests.sh"})
_HANDLER_TESTS = "tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py"
_HANDLER = "src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py"
_LLM_QA = "./scripts/qa/llm_qa.py"
_PLAN = "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate"
_ACTIVATE = Path(sys.prefix) / "bin" / "activate"


def _everyday_commands() -> list[str]:
    commands = [
        # Targeted pytest.
        f"pytest {_HANDLER_TESTS} -q",
        f"pytest {_HANDLER_TESTS} -x -q --no-header",
        f"pytest {_HANDLER_TESTS}::TestTheCodeFileReaderIsBounded -q",
        f"pytest {_HANDLER_TESTS} -k 'memo or verdict' -q",
        f"python -m pytest {_HANDLER_TESTS} -q",
        f"python3 -m pytest -q {_HANDLER_TESTS} tests/unit/utils/test_shell_segmentation.py",
        "pytest tests/unit/qa -q",
        "pytest tests/unit/qa/test_llm_qa_main_moved.py -q",
        "pytest tests/unit/qa/test_llm_qa*.py -q",
        "pytest tests/unit/utils -q",
        "pytest tests/unit/handlers/pre_tool_use -q -n 4",
        "pytest tests/integration/test_full_qa_gate_is_never_deadlocked.py -q",
        "pytest tests/unit/qa -q --lf",
        "pytest tests/unit/qa -q --ff -x",
        "pytest tests/unit/qa -q -p no:randomly",
        "pytest tests/unit/qa -q --tb=short",
        "pytest tests/unit/qa -q --timeout=120",
        "pytest tests/unit/qa -q -o addopts=''",
        "pytest tests/unit/qa --co -q",
        "pytest --collect-only tests",
        "pytest --version",
        "pytest --help",
        f"pytest {_HANDLER_TESTS} -q 2>&1 | bin/echd-capture 30",
        f"pytest {_HANDLER_TESTS} -q > untracked/scratch/out.txt 2>&1",
        f"timeout 600 pytest {_HANDLER_TESTS} -q",
        "cd tests/unit/qa && pytest test_run_changed_tests.py -q",
        f"PYTHONPATH=src pytest {_HANDLER_TESTS} -q",
        f"env PYTHONPATH=src pytest {_HANDLER_TESTS} -q",
        "pytest tests/unit/qa/test_run_changed_tests.py tests/unit/qa/test_llm_qa_changed.py",
        "pytest -q tests/unit/daemon/test_cli_enforcement_status.py",
        f"pytest {_HANDLER_TESTS} --cov=src/claude_code_hooks_daemon/handlers "
        "--cov-report=term-missing -q",
        "git diff --name-only main...HEAD -- tests | xargs -r pytest -q",
        'git diff --name-only "$(git merge-base main HEAD)" -- tests | xargs -r pytest -q',
        'for f in $(git diff --name-only main -- tests); do pytest -q "$f"; done',
        f"for i in 1 2 3; do pytest {_HANDLER_TESTS} -q -x || break; done",
        f"set -euo pipefail; pytest {_HANDLER_TESTS} -q; ruff check {_HANDLER}",
        # The named llm_qa tools, and a read-only run.
        f"{_LLM_QA} changed",
        f"{_LLM_QA} lint",
        f"{_LLM_QA} lint type_check",
        f"{_LLM_QA} type_check pyright",
        f"{_LLM_QA} format",
        f"{_LLM_QA} shell_check",
        f"{_LLM_QA} --read-only all",
        f"{_LLM_QA} --help",
        f"{_LLM_QA} main-moved",
        "python3 scripts/qa/llm_qa.py changed",
        f"{_LLM_QA} changed --range main..HEAD",
        # Static tools.
        f"ruff check {_HANDLER}",
        f"ruff check --fix {_HANDLER}",
        f"ruff format --check {_HANDLER}",
        "ruff check src tests",
        f"black --check {_HANDLER}",
        f"black {_HANDLER} {_HANDLER_TESTS}",
        f"mypy {_HANDLER}",
        "mypy src/claude_code_hooks_daemon --strict",
        f"pyright {_HANDLER}",
        "shellcheck scripts/qa/*.sh",
        "bandit -r src -q",
        f"python -m py_compile {_HANDLER}",
        # Repository scripts run as documented.
        "./scripts/qa/run_lint.sh",
        "./scripts/qa/run_type_check.sh",
        "./scripts/qa/run_format_check.sh",
        "./scripts/qa/run_shell_check.sh",
        "bash scripts/qa/run_security_check.sh",
        "./scripts/qa/run_autofix.sh",
        "./scripts/qa/check_canonical_callers.sh",
        # `bin/hooks-daemon` itself: round 9 B1's UNSEEN residual (the CLI's
        # own two-hop `cd` chain, unresolved by this handler's nested-
        # substitution walk) is ALLOWED, not denied, per the round 9d
        # coordinator ruling -- UNSEEN code is advisory-only now that the
        # sink (the host-wide full-QA lock) is the guarantee. See PLAN.md's
        # "Round 9" section.
        "bin/hooks-daemon status",
        "bin/hooks-daemon restart",
        "./bin/hooks-daemon explain-rule R-SUBAGENT-FULL-QA",
        "bin/hooks-daemon find-plan 463",
        'CLAUDE/Plan/mkplan.bash "a-new-plan"',
        f"CLAUDE/Plan/mkplan.bash --journal {_PLAN} Review untracked/scratch/journal.txt",
        # git and gh.
        "git status",
        "git status --short",
        "git log --oneline -20",
        "git log --oneline main..HEAD",
        "git diff --stat main...HEAD",
        f"git diff HEAD~1 -- {_HANDLER}",
        "git add -A && git commit -m 'Plan 00463: fix the pytest tests message'",
        "git commit -m 'run ./scripts/qa/llm_qa.py all on the coordinator'",
        "git show --stat HEAD",
        "git merge-base main HEAD",
        "git rev-parse --short HEAD",
        "git branch --show-current",
        "git fetch origin main",
        "git rebase main",
        "git merge --no-ff main -m 'Merge main'",
        "git worktree list",
        f"git blame -L 3640,3700 {_HANDLER}",
        "gh pr view 12 --comments",
        "gh issue view 55 --comments",
        "gh pr list --state open",
        "gh pr create --title 'x' --body 'Runs pytest tests in CI'",
        "gh run list --limit 5",
        # Reading, grepping and mentioning.
        f"grep -n 'pytest tests' {_HANDLER}",
        "grep -rn 'llm_qa.py all' CLAUDE/QA.md",
        "rg -n 'run_all.sh' scripts",
        "echo 'run pytest tests on the coordinator'",
        "printf '%s\\n' 'llm_qa.py all'",
        "cat scripts/qa/run_all.sh",
        "less CLAUDE/QA.md",
        f"awk 'NR>=3640 && NR<=3700' {_HANDLER}",
        f"wc -l {_HANDLER} {_HANDLER_TESTS}",
        "ls tests/unit/qa",
        "find tests/unit/qa -name 'test_*.py'",
        "find tests/unit/qa -name 'test_llm_qa*.py' -exec pytest -q {} +",
        "find src -name '*.py' -newer pyproject.toml",
        "diff -u a.txt b.txt",
        "jq . untracked/qa/lint.json",
        "cat untracked/qa/tests.json | jq '.summary'",
        "python3 -c 'import sys; print(sys.version)'",
        "python3 -c 'import pytest; print(pytest.__version__)'",
        "man pytest",
        "which pytest",
        "type pytest",
        "command -v pytest",
        # Commands that only set up the environment (review 7 m2).
        'eval "$(ssh-agent -s)" && ssh-add -l',
        'eval "$(pyenv init -)"; pytest tests/unit/qa -q',
        "source <(kubectl completion bash)",
        'eval "$(direnv export bash)"',
        f"source {_ACTIVATE} && pytest tests/unit/qa -q",
        f". {_ACTIVATE}; ruff check src",
        # Everything else.
        "sleep 1",
        "mkdir -p untracked/scratch/x",
        "touch untracked/scratch/x/y",
        "cp untracked/scratch/a untracked/scratch/b",
        "uv run pytest tests/unit/qa -q",
        "python scripts/setup_worktree.sh --help",
    ]
    qa_scripts = _REPO_ROOT / "scripts" / "qa"
    for script in sorted(qa_scripts.glob("*.py")):
        commands.append(f"python scripts/qa/{script.name} --help")
        commands.append(f"python3 scripts/qa/{script.name}")
    for script in sorted(qa_scripts.glob("*.sh")):
        if script.name not in _FULL_BY_DESIGN:
            commands.append(f"./scripts/qa/{script.name}")
    skills_dir = _REPO_ROOT / ".claude" / "skills"
    for invoke in sorted(skills_dir.glob("*/invoke.sh")):
        commands.append(f"bash {invoke.relative_to(_REPO_ROOT).as_posix()}")
    return commands


def _live_patterns() -> list[FullQaPattern]:
    config = ConfigLoader.load(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    options: dict[str, Any] = config["handlers"]["pre_tool_use"]["subagent_full_qa_blocker"][
        "options"
    ]
    patterns, problems = parse_full_qa_patterns(options["full_qa_patterns"])
    assert not problems, problems
    return patterns


def _live_handler() -> SubagentFullQaBlockerHandler:
    """The handler as this repository's own config configures it (Decision.handle level).

    A DIFFERENT question from ``_live_patterns()``: that answers "does this
    handler's parser SEE this as a full run"; this answers "does the sub-
    agent's command actually get DENIED" -- and per the round 9d coordinator
    ruling those two questions diverge for UNSEEN code (allowed, advisory
    only) while agreeing for a positively SEEN one (denied).
    """
    config = ConfigLoader.load(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    options: dict[str, Any] = config["handlers"]["pre_tool_use"]["subagent_full_qa_blocker"][
        "options"
    ]
    handler = SubagentFullQaBlockerHandler()
    handler._full_qa_patterns = options["full_qa_patterns"]
    handler._targeted_qa_commands = options.get("targeted_qa_commands", [])
    return handler


def _decision(command: str) -> Decision:
    hook_input = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(_REPO_ROOT),
    }
    return _live_handler().handle(hook_input).decision


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Every fixture file, executable, with each command's ``@FX@`` pointing here."""
    directory = tmp_path_factory.mktemp("full_qa_corpus")
    for name, text in {**_python_sources(), **_SHELL_SOURCES}.items():
        path = directory / name
        path.write_text(text.replace(_FX, str(directory)), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return directory


@pytest.fixture(scope="module")
def patterns() -> list[FullQaPattern]:
    return _live_patterns()


@pytest.mark.parametrize(("command", "full"), _corpus_rows())
def test_the_review_8_corpus_gets_its_verdict(
    command: str, full: bool, fixture_dir: Path, patterns: list[FullQaPattern]
) -> None:
    resolved = command.replace(_FX, str(fixture_dir))
    match = find_full_qa_invocation(resolved, patterns, cwd=_REPO_ROOT)
    assert (match is not None) is full, (resolved, match)


@pytest.mark.parametrize("command", _everyday_commands())
def test_an_everyday_sub_agent_command_is_allowed(command: str) -> None:
    """Never DENIED -- whether this handler's parser sees the command in full,
    or judges it UNSEEN (round 9d: UNSEEN is advisory-only, never a deny)."""
    assert _decision(command) is Decision.ALLOW, command


class TestUnseenScriptsAreAllowedNotDenied:
    """Round 9d coordinator ruling: UNSEEN code is ALLOWED, with an advisory.

    ``bin/hooks-daemon`` is review 9 B1's residual, narrowed in round 9c: its
    own self-location loop resolves, but a later two-hop ``cd`` chain in the
    same script reaches a variable this handler's nested-substitution walk
    cannot see, so ``find_full_qa_invocation`` still judges it UNSEEN (see
    ``fail_closed`` on its match). What changed this round is the
    CONSEQUENCE: the sink (the host-wide full-QA lock) is the guarantee now,
    so this handler no longer denies what it merely could not see -- only a
    POSITIVELY SEEN full run still does (``TestTheDenial`` in
    ``test_subagent_full_qa_blocker.py``).
    """

    @pytest.mark.parametrize(
        "command",
        [
            "bin/hooks-daemon status",
            "bin/hooks-daemon restart",
            "./bin/hooks-daemon explain-rule R-SUBAGENT-FULL-QA",
            "bin/hooks-daemon find-plan 463",
        ],
    )
    def test_still_judged_unseen_by_the_parser(
        self, command: str, patterns: list[FullQaPattern]
    ) -> None:
        match = find_full_qa_invocation(command, patterns, cwd=_REPO_ROOT)
        assert match is not None, command
        assert match.fail_closed

    @pytest.mark.parametrize(
        "command",
        [
            "bin/hooks-daemon status",
            "bin/hooks-daemon restart",
            "./bin/hooks-daemon explain-rule R-SUBAGENT-FULL-QA",
            "bin/hooks-daemon find-plan 463",
        ],
    )
    def test_allowed_at_the_handler_decision_level(self, command: str) -> None:
        assert _decision(command) is Decision.ALLOW, command
