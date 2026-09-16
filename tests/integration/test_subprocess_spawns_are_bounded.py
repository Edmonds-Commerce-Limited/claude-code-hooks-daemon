"""Every subprocess spawn in `src/` carries a timeout (Plan 00412, class 15).

The class is `unbounded-work-on-input-not-sized`: a call that can wait for ever
on something the caller does not control. `test_git_spawns_are_bounded` covers
git by routing it through one bounded runner, but git is not the only thing this
daemon spawns — and a hook handler that blocks has no timeout of its own to fall
back on. It blocks the agent's tool call, indefinitely.

**The measured state when this guard was written**: 16 boundable spawns in
`src/`, 14 already carrying a timeout. The convention was established and two
sites had drifted from it — `daemon/background_harvester.py` spawning `ps` and
`daemon/cli.py` spawning `gh run list`. Both are the shape that hurts most: the
harvester one runs from a cron tick, and `gh` reaches the NETWORK, where "slow"
is not a bug but the normal weather.

**Why `Popen` is excluded, and it is not an oversight.** `Popen` takes no
`timeout` at construction; its bound is set later at `communicate(timeout=…)` or
`wait(timeout=…)`. `install/transport_verify.py` does exactly that, correctly,
and a rule that treated `Popen` like `run` would report it as a violation — then
someone would switch the rule off. Expressing "this Popen is bounded somewhere
downstream" needs dataflow this deliberately shallow AST subset does not do, so
the honest move is to say so rather than guess. That leaves `Popen` as a real
gap in the guard, recorded here rather than papered over.

**Why a test rather than a `scripts/qa/` checker**: the same reason its sibling
gives — a test needs no wiring to be binding, runs in the QA suite and CI by
construction, and cannot publish a verdict under a key no consumer reads.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

from tests.subprocess_ast import spawner_name, subprocess_bindings

_SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "claude_code_hooks_daemon"

#: The parameter that bounds a spawn.
_TIMEOUT: Final[str] = "timeout"

#: Spawners that accept `timeout` at the call itself. `Popen` is absent for the
#: reason the module docstring gives: it is bounded downstream, not here.
_BOUNDABLE: Final[frozenset[str]] = frozenset({"run", "call", "check_call", "check_output"})

#: Spawn sites permitted to run unbounded, each with the reason it is exempt.
#: A new entry is a deliberate decision that must carry its justification —
#: without one this degrades into a list of whatever failed last.
_EXEMPT: Final[dict[str, str]] = {}


class _UnboundedSpawn(NamedTuple):
    """A spawn in the source tree with no timeout."""

    relative_path: str
    line: int
    spawner: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.line} — subprocess.{self.spawner}(...) with no timeout"


def _unbounded_spawns(source_root: Path) -> list[_UnboundedSpawn]:
    """Every boundable spawn in ``source_root`` that carries no timeout."""
    found: list[_UnboundedSpawn] = []
    for module in sorted(source_root.rglob("*.py")):
        relative = module.relative_to(source_root).as_posix()
        if relative in _EXEMPT:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        bindings = subprocess_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            spawner = spawner_name(node, bindings)
            if spawner not in _BOUNDABLE:
                continue
            if any(keyword.arg == _TIMEOUT for keyword in node.keywords):
                continue
            found.append(_UnboundedSpawn(relative, node.lineno, str(spawner)))
    return found


class TestEverySpawnIsBounded:
    """The guard. An unbounded spawn fails here rather than hanging an agent."""

    def test_no_module_spawns_without_a_timeout(self) -> None:
        violations = _unbounded_spawns(_SRC_ROOT)

        assert violations == [], (
            "These spawns can wait for ever on something the caller does not "
            "control. A hook handler that blocks has no timeout of its own — it "
            "blocks the agent's tool call indefinitely, with no error to "
            "read.\n\n  "
            + "\n  ".join(str(violation) for violation in violations)
            + "\n\nFix: pass `timeout=<seconds>` and handle "
            "`subprocess.TimeoutExpired`. If a call genuinely must run "
            "unbounded, add it to `_EXEMPT` with the reason."
        )


class TestTheScannerIsNotVacuous:
    """An assertion that a list is empty is what a BROKEN scanner also produces.

    Every case below writes the shape to a scratch tree and runs the real
    scanner over it, so the guard is shown to detect what it claims to rather
    than assumed to.
    """

    def _scan(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "offender.py").write_text(source, encoding="utf-8")
        return [spawn.spawner for spawn in _unbounded_spawns(tmp_path)]

    def test_an_untimed_run_is_caught(self, tmp_path: Path) -> None:
        source = 'import subprocess\nsubprocess.run(["ps", "-e"], check=True)\n'

        assert self._scan(tmp_path, source) == ["run"]

    def test_a_timed_run_is_not_flagged(self, tmp_path: Path) -> None:
        source = 'import subprocess\nsubprocess.run(["ps"], timeout=5, check=True)\n'

        assert self._scan(tmp_path, source) == []

    def test_check_output_is_covered(self, tmp_path: Path) -> None:
        """`run` is not the only way to block for ever."""
        source = 'import subprocess\nsubprocess.check_output(["gh", "api", "x"])\n'

        assert self._scan(tmp_path, source) == ["check_output"]

    def test_an_aliased_module_import_does_not_escape(self, tmp_path: Path) -> None:
        """The shared resolver's whole reason for existing, asserted here too."""
        source = 'import subprocess as sp\nsp.run(["ps"], check=True)\n'

        assert self._scan(tmp_path, source) == ["run"]

    def test_an_aliased_from_import_reports_its_real_spawner(self, tmp_path: Path) -> None:
        """`run as launch` must report `run`, not the local alias.

        The message names the spawner so a reader can find the call. Reporting
        the alias would send them looking for `subprocess.launch`, which does
        not exist.
        """
        source = 'from subprocess import run as launch\nlaunch(["ps"])\n'

        assert self._scan(tmp_path, source) == ["run"]

    def test_a_bare_run_from_elsewhere_is_not_flagged(self, tmp_path: Path) -> None:
        """Only names bound to `subprocess` count — no guessing by name alone."""
        source = 'from mylib import run\nrun(["ps"])\n'

        assert self._scan(tmp_path, source) == []


class TestPopenIsExcludedDeliberately:
    """Pinning the documented gap, so it stays a decision rather than a bug.

    `Popen` is bounded at `communicate(timeout=…)`, not at construction. Without
    this test the exclusion looks like an omission, and the next reader
    "fixes" it — which would flag `install/transport_verify.py`, a correctly
    bounded call, and earn the whole guard a reputation for crying wolf.
    """

    def _scan(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "offender.py").write_text(source, encoding="utf-8")
        return [spawn.spawner for spawn in _unbounded_spawns(tmp_path)]

    def test_a_popen_is_not_flagged_even_with_no_timeout(self, tmp_path: Path) -> None:
        source = 'import subprocess\nproc = subprocess.Popen(["ps"])\n'

        assert self._scan(tmp_path, source) == []

    def test_the_real_bounded_popen_site_is_not_flagged(self) -> None:
        """The concrete call the exclusion exists to protect."""
        violations = _unbounded_spawns(_SRC_ROOT)

        assert not [v for v in violations if v.relative_path == "install/transport_verify.py"]
