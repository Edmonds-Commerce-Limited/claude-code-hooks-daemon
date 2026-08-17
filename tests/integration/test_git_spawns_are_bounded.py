"""Every git spawn goes through the one bounded runner (Plan 00246).

`utils/git_repo.py` has stated since Plan 00113 that "new git operations are
added as methods on `GitRepo`, not by re-implementing
`subprocess.run(["git", ...])` in each caller". Fifteen files did it anyway, and
the cost was not stylistic: two properties every invocation needs — declining
git's OPTIONAL index lock, and carrying a timeout — had to be remembered
individually, so a one-line fix became a thirty-site sweep.

This is the guard for that, and it is the actual deliverable of the plan. DBF
(`CLAUDE.md` Core Standard 15): the defect worth fixing is the missing check that
let thirty call sites drift, not the thirty call sites.

**Why a test rather than a `scripts/qa/` checker**: a test needs no wiring to be
binding. It runs in the QA suite and in CI by construction, and cannot publish
its verdict under a key no consumer reads — the failure mode Plan 00244 hit with
a freshly-added checker.

**What it can and cannot see**: it matches the mechanically-checkable shape — a
`subprocess` call whose argv is a list literal beginning with `"git"`. An argv
built up in a variable escapes it. That is the same deliberate subset
`check_magic_values.py` targets, and the same trade-off: a check that fires only
on unambiguous shapes stays enabled, and one that guesses gets disabled.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

_SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "claude_code_hooks_daemon"

#: `subprocess` entry points that start a process.
_SPAWNING_CALLS: Final[frozenset[str]] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)

_GIT: Final[str] = "git"

#: Files permitted to spawn git directly, each with the reason it is exempt.
#: A new entry is a deliberate decision that must carry its justification —
#: without one this degrades into a list of whatever failed last.
_EXEMPT: Final[dict[str, str]] = {
    "utils/git_repo.py": (
        "THE bounded runner itself — the one place git is spawned, where the "
        "declined index lock and the timeout are applied"
    ),
}


class _Spawn(NamedTuple):
    """A direct git spawn found in the source tree."""

    relative_path: str
    line: int
    argv_head: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.line} — {self.argv_head}"


def _argv_starts_with_git(call: ast.Call) -> str | None:
    """Return a readable argv head when this call's argv literal starts with git.

    Only a list/tuple literal is inspected. `["git", "status"]` is unambiguous;
    a name referring to a list built elsewhere is not, and guessing is what makes
    a checker untrustworthy.
    """
    if not call.args:
        return None
    argv = call.args[0]
    if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
        return None
    first = argv.elts[0]
    if not isinstance(first, ast.Constant) or first.value != _GIT:
        return None
    words = [
        element.value
        for element in argv.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
    return " ".join(words)


def _is_subprocess_spawn(call: ast.Call) -> bool:
    """True for `subprocess.<spawner>(...)` calls."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _SPAWNING_CALLS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _direct_git_spawns(source_root: Path) -> list[_Spawn]:
    """Every direct git spawn in `source_root`, exemptions removed."""
    found: list[_Spawn] = []
    for module in sorted(source_root.rglob("*.py")):
        relative = module.relative_to(source_root).as_posix()
        if relative in _EXEMPT:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_subprocess_spawn(node):
                continue
            argv_head = _argv_starts_with_git(node)
            if argv_head is not None:
                found.append(_Spawn(relative, node.lineno, argv_head))
    return found


class TestEveryGitSpawnGoesThroughTheBoundedRunner:
    """The guard. A new direct spawn fails here rather than in a user's repo."""

    def test_no_module_spawns_git_directly(self) -> None:
        violations = _direct_git_spawns(_SRC_ROOT)

        assert violations == [], (
            "These modules spawn git directly instead of via "
            "`utils.git_repo.run_git`, so they neither decline git's optional "
            "index lock nor inherit a timeout. A plain `git status` REWRITES "
            "the index, taking `.git/index.lock` in the working tree the agent "
            "is using — see Plan 00246.\n\n  "
            + "\n  ".join(str(violation) for violation in violations)
            + "\n\nFix: call `run_git(cwd, *args, timeout=...)`. If a call "
            "genuinely must spawn git itself, add it to `_EXEMPT` with the "
            "reason."
        )

    def test_the_scanner_actually_finds_the_shape_it_claims_to(self, tmp_path: Path) -> None:
        """Control: a guard that silently matches nothing passes forever.

        `test_no_module_spawns_git_directly` is an assertion that a list is
        empty — which is exactly what a broken scanner also produces. This
        proves the scanner detects the shape, and that the exemption mechanism
        is what suppresses it rather than a parsing failure.
        """
        offender = tmp_path / "offender.py"
        offender.write_text(
            "import subprocess\n" 'subprocess.run(["git", "status", "--porcelain"], check=False)\n',
            encoding="utf-8",
        )

        found = _direct_git_spawns(tmp_path)

        assert [spawn.argv_head for spawn in found] == ["git status --porcelain"]

    def test_a_non_git_subprocess_is_not_flagged(self, tmp_path: Path) -> None:
        """The scanner must not object to every subprocess in the codebase."""
        innocent = tmp_path / "innocent.py"
        innocent.write_text(
            "import subprocess\nsubprocess.run(['ruff', 'check'], check=False)\n",
            encoding="utf-8",
        )

        assert _direct_git_spawns(tmp_path) == []
