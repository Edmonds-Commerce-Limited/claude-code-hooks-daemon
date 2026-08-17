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
`subprocess` spawner call whose argv is a list literal beginning with `"git"`,
reached through any of the ordinary import idioms (`subprocess.run`,
`sp.run` via an alias, or a `from subprocess import run` name), with argv passed
positionally or as `args=`. An argv built up in a variable escapes it, as does a
first element that is not a literal `"git"` (`shutil.which("git")`,
`"/usr/bin/git"`). That is the same deliberate subset `check_magic_values.py`
targets, and the same trade-off: a check that fires only on unambiguous shapes
stays enabled, and one that guesses gets disabled.

The import-idiom coverage was added by Plan 00248 after a review demonstrated the
escapes by execution. It is worth being precise about why those three counted and
the others did not: an alias import is not an evasion, it is how Python code is
written, and `sp.run(["git", ...])` is exactly as unambiguous as the spelled-out
form. `shutil.which("git")` genuinely is ambiguous to a reader of the AST alone.

**Scope**: `src/` only. `scripts/qa/` also spawns git directly and untimed; none
of those calls touches the index today (`log`, `for-each-ref`), but the guard
would not notice if one started to.
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

#: `subprocess.run`'s own name for its argv parameter, so a caller may pass argv
#: as a keyword and still be making an entirely ordinary call.
_ARGV_KEYWORD: Final[str] = "args"

#: The module whose spawners this guard is about.
_SUBPROCESS: Final[str] = "subprocess"

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


def _argv_node(call: ast.Call) -> ast.expr | None:
    """The expression holding this call's argv, positional or `args=`."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == _ARGV_KEYWORD:
            return keyword.value
    return None


def _argv_starts_with_git(call: ast.Call) -> str | None:
    """Return a readable argv head when this call's argv literal starts with git.

    Only a list/tuple literal is inspected. `["git", "status"]` is unambiguous;
    a name referring to a list built elsewhere is not, and guessing is what makes
    a checker untrustworthy.

    Positional AND `args=`: the keyword is the parameter's documented name, so
    `subprocess.run(args=["git", ...])` is exactly as clear as the positional
    form — reading only `call.args` let it through (Plan 00248 F5).
    """
    argv = _argv_node(call)
    if argv is None:
        return None
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


class _SubprocessBindings(NamedTuple):
    """The local names in one module that reach a `subprocess` spawner.

    Resolved per module rather than assumed, because the first version of this
    guard hard-coded the name `subprocess` and so missed every ordinary
    alternative: `import subprocess as sp`, `from subprocess import run`, and
    `from subprocess import run as launch` (Plan 00248 F5). Names are collected
    from the module's own imports, so nothing is inferred from spelling alone —
    a project-local `run` from elsewhere is still not a subprocess spawn.
    """

    #: Names bound to the `subprocess` MODULE — `subprocess`, `sp`, …
    modules: frozenset[str]
    #: Names bound directly to a spawner — `run`, `launch`, …
    spawners: frozenset[str]


def _subprocess_bindings(tree: ast.Module) -> _SubprocessBindings:
    """Every local name in `tree` that leads to a `subprocess` spawner."""
    modules: set[str] = set()
    spawners: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _SUBPROCESS:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == _SUBPROCESS:
            for alias in node.names:
                if alias.name in _SPAWNING_CALLS:
                    spawners.add(alias.asname or alias.name)
    return _SubprocessBindings(frozenset(modules), frozenset(spawners))


def _is_subprocess_spawn(call: ast.Call, bindings: _SubprocessBindings) -> bool:
    """True for a call that reaches a `subprocess` spawner in this module."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr in _SPAWNING_CALLS
            and isinstance(func.value, ast.Name)
            and func.value.id in bindings.modules
        )
    return isinstance(func, ast.Name) and func.id in bindings.spawners


def _direct_git_spawns(source_root: Path) -> list[_Spawn]:
    """Every direct git spawn in `source_root`, exemptions removed."""
    found: list[_Spawn] = []
    for module in sorted(source_root.rglob("*.py")):
        relative = module.relative_to(source_root).as_posix()
        if relative in _EXEMPT:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        bindings = _subprocess_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_subprocess_spawn(node, bindings):
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


class TestOrdinaryImportIdiomsDoNotEscape:
    """Plan 00248 F5: three shapes walked straight past the first scanner.

    None of them is an attempt to bypass anything — they are the ordinary ways
    Python code imports and calls `subprocess`, and a future author would reach
    for any of them without a thought. Each is also UNAMBIGUOUS, which is the
    line this scanner's docstring draws: argv assembled in a variable is left
    alone because reading it would mean guessing, but `sp.run(["git", ...])` is
    exactly as clear as `subprocess.run(["git", ...])`.

    The escapes were found by execution, not by reading: each shape below was
    written to a scratch file and run through the real scanner.
    """

    def _scan_source(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "offender.py").write_text(source, encoding="utf-8")
        return [spawn.argv_head for spawn in _direct_git_spawns(tmp_path)]

    def test_an_aliased_module_import_is_caught(self, tmp_path: Path) -> None:
        source = 'import subprocess as sp\nsp.run(["git", "status"], check=False)\n'

        assert self._scan_source(tmp_path, source) == ["git status"]

    def test_a_from_import_of_the_spawner_is_caught(self, tmp_path: Path) -> None:
        source = 'from subprocess import run\nrun(["git", "status"], check=False)\n'

        assert self._scan_source(tmp_path, source) == ["git status"]

    def test_an_aliased_from_import_is_caught(self, tmp_path: Path) -> None:
        source = 'from subprocess import run as launch\nlaunch(["git", "status"])\n'

        assert self._scan_source(tmp_path, source) == ["git status"]

    def test_argv_passed_as_a_keyword_is_caught(self, tmp_path: Path) -> None:
        """`args=` is the parameter's real name, so this is a documented call."""
        source = 'import subprocess\nsubprocess.run(args=["git", "status"], check=False)\n'

        assert self._scan_source(tmp_path, source) == ["git status"]

    def test_a_bare_run_from_elsewhere_is_not_flagged(self, tmp_path: Path) -> None:
        """Only names bound to `subprocess` count — no guessing by name alone.

        A project-local `run(["git", ...])` helper that already goes through the
        bounded runner would otherwise be flagged for the shape of its argv.
        """
        source = 'from mylib import run\nrun(["git", "status"])\n'

        assert self._scan_source(tmp_path, source) == []

    def test_a_non_git_call_through_an_alias_is_not_flagged(self, tmp_path: Path) -> None:
        source = 'import subprocess as sp\nsp.run(["ruff", "check"])\n'

        assert self._scan_source(tmp_path, source) == []
