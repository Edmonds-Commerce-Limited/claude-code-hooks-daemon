"""A PATH-mutating function must not execute a bare command name.

Plan 00412 class 3, `enforcement-path-executes-unverified-code`: the guard
process loads or spawns code whose origin is not tracked in this repository, not
pinned by its lockfile, and not integrity-checked at the moment of use. Severity
CRITICAL, corroborated across four reports, because the outcome is code
execution inside the process that enforces every other guard.

**The narrow, near-free form the worklist asks for first.** The full class needs
every execution and import sink audited, and D-EVAL records that a naive
sink-grep flags constrained `importlib` calls at `config/validator.py:148,169`
— so the general rule needs allowances, "and that allowance is itself where a
future defect could hide". This Detector takes the high-yield conjunction
instead:

    a subprocess call whose argv[0] is a BARE NAME
    AND the same function mutates env["PATH"]

Neither half is a defect alone. A bare name resolved from the daemon's own
inherited PATH is ordinary; mutating PATH to reach a known absolute binary is
ordinary. Together they mean the function CHOSE the directory that will resolve
the name — and in the instance this was written for, that directory belongs to
the tree under review.

**The live instance** is `validate_eslint_on_write.py`: it prepends the guarded
project's `node_modules/.bin` to PATH, then spawns bare `tsx` with `cwd` set to
that project to run `scripts/eslint-wrapper.ts`, a file this repository does not
ship. Any malicious package in a client's npm tree gets code execution in a
daemon subprocess on the next TypeScript write. Its `nosec B603 - eslint/npx are
trusted tools` comment is the finding in miniature: the tool NAMES are trusted,
the binaries those names resolve to are supplied by the tree under review.

Committed RED, before the fix, per Defence Before Fix -- so the class is watched
from the moment it is named rather than from the moment a register says the work
was done.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

#: The env key whose mutation makes a bare name resolve somewhere chosen.
_PATH_KEY: Final[str] = "PATH"

#: subprocess entry points that take an argv sequence as their first argument.
_SUBPROCESS_SINKS: Final[frozenset[str]] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)


class Violation(NamedTuple):
    """One function that both steers PATH and executes a name it does not pin."""

    module: Path
    function: str
    line: int
    argv0: str

    def __str__(self) -> str:
        relative = self.module.relative_to(_REPO_ROOT)
        return f"{relative}:{self.line} {self.function}() executes bare {self.argv0!r}"


def _is_bare_name(value: str) -> bool:
    """Whether ``value`` names a command PATH has to resolve.

    A path with a separator -- absolute or relative -- names a file directly, so
    no PATH lookup happens and the directory prepended above cannot redirect it.
    That is exactly the fix this Detector wants to see, so it must read as clean.
    """
    return bool(value) and "/" not in value and not value.startswith(".")


def _mutates_path(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the function assigns to a ``[...]["PATH"]`` subscript.

    Deliberately narrow: this is the shape the live instance uses, and a rule
    that also guessed at `update()` and `setdefault()` would report shapes no
    measurement has seen. Class 6 applies -- the narrowness is recorded in the
    module docstring rather than hidden.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == _PATH_KEY
            ):
                return True
    return False


def _list_literals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.List]:
    """Names bound to a list literal anywhere in ``function``.

    An argv list is usually built into a local and passed by name, so resolving
    the binding is what lets the Detector see argv[0] at all.
    """
    bindings: dict[str, ast.List] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value
    return bindings


def _argv0(argument: ast.expr, bindings: dict[str, ast.List]) -> str | None:
    """The first element of an argv sequence, when it is a string constant."""
    literal: ast.List | None = None
    if isinstance(argument, ast.List):
        literal = argument
    elif isinstance(argument, ast.Name):
        literal = bindings.get(argument.id)
    if literal is None or not literal.elts:
        return None
    first = literal.elts[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _subprocess_calls(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """Calls to a subprocess entry point that takes an argv sequence."""
    calls: list[ast.Call] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_SINKS:
            calls.append(node)
        elif isinstance(func, ast.Name) and func.id in _SUBPROCESS_SINKS:
            calls.append(node)
    return calls


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _violations_in(module: Path) -> list[Violation]:
    try:
        tree = ast.parse(module.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        # A module that cannot be parsed cannot be cleared either. Reported as
        # no findings, but the count below reports how many were scanned, so a
        # collapse in coverage is visible rather than silent.
        return []

    found: list[Violation] = []
    for function in _functions(tree):
        if not _mutates_path(function):
            continue
        bindings = _list_literals(function)
        for call in _subprocess_calls(function):
            if not call.args:
                continue
            name = _argv0(call.args[0], bindings)
            if name is not None and _is_bare_name(name):
                found.append(
                    Violation(
                        module=module,
                        function=function.name,
                        line=call.lineno,
                        argv0=name,
                    )
                )
    return found


def _scan() -> tuple[list[Violation], int]:
    """Every violation in the daemon's own source, and how many modules were read."""
    modules = sorted(_SOURCE_ROOT.rglob("*.py"))
    found: list[Violation] = []
    for module in modules:
        found.extend(_violations_in(module))
    return found, len(modules)


class TestTheDetectorIsNotVacuous:
    """A Detector that cannot fire is a register entry, not a defence.

    Every assertion below is on synthetic source, so it holds regardless of what
    the real tree contains -- including after the live instance is fixed.
    """

    def test_it_fires_on_the_conjunction(self, tmp_path: Path) -> None:
        module = tmp_path / "sink.py"
        module.write_text(
            "import os, subprocess\n"
            "def run_it(bin_dir):\n"
            "    env = os.environ.copy()\n"
            '    env["PATH"] = str(bin_dir) + ":" + env["PATH"]\n'
            '    subprocess.run(["tsx", "wrapper.ts"], env=env)\n',
            encoding="utf-8",
        )

        violations = _violations_in(module)

        assert [v.argv0 for v in violations] == ["tsx"]

    def test_an_absolute_argv0_is_clean(self, tmp_path: Path) -> None:
        """The fix must read as clean, or the Detector blocks its own remedy."""
        module = tmp_path / "pinned.py"
        module.write_text(
            "import os, subprocess\n"
            "def run_it(bin_dir):\n"
            "    env = os.environ.copy()\n"
            '    env["PATH"] = str(bin_dir) + ":" + env["PATH"]\n'
            '    subprocess.run(["/usr/bin/tsx", "wrapper.ts"], env=env)\n',
            encoding="utf-8",
        )

        assert _violations_in(module) == []

    def test_a_bare_name_without_a_path_mutation_is_clean(self, tmp_path: Path) -> None:
        """Half the conjunction is ordinary and must not be reported."""
        module = tmp_path / "plain.py"
        module.write_text(
            "import subprocess\n" "def run_it():\n" '    subprocess.run(["git", "status"])\n',
            encoding="utf-8",
        )

        assert _violations_in(module) == []

    def test_a_path_mutation_without_an_execution_is_clean(self, tmp_path: Path) -> None:
        module = tmp_path / "envonly.py"
        module.write_text(
            "import os\n"
            "def prepare(bin_dir):\n"
            "    env = os.environ.copy()\n"
            '    env["PATH"] = str(bin_dir)\n'
            "    return env\n",
            encoding="utf-8",
        )

        assert _violations_in(module) == []

    def test_an_argv_list_bound_to_a_name_is_still_resolved(self, tmp_path: Path) -> None:
        """Real code builds the list first; reading only inline literals would
        miss the live instance entirely."""
        module = tmp_path / "indirect.py"
        module.write_text(
            "import os, subprocess\n"
            "def run_it(bin_dir):\n"
            '    command = ["tsx", "wrapper.ts"]\n'
            "    env = os.environ.copy()\n"
            '    env["PATH"] = str(bin_dir)\n'
            "    subprocess.run(command, env=env)\n",
            encoding="utf-8",
        )

        assert [v.argv0 for v in _violations_in(module)] == ["tsx"]

    def test_a_mutation_of_another_env_key_is_clean(self, tmp_path: Path) -> None:
        """Only PATH decides where a bare name resolves."""
        module = tmp_path / "otherkey.py"
        module.write_text(
            "import os, subprocess\n"
            "def run_it():\n"
            "    env = os.environ.copy()\n"
            '    env["NODE_ENV"] = "production"\n'
            '    subprocess.run(["tsx"], env=env)\n',
            encoding="utf-8",
        )

        assert _violations_in(module) == []


class TestTheDaemonNeverExecutesANameItDidNotPin:
    """The live assertion. RED until class 3's first instance is fixed."""

    def test_no_path_mutating_function_executes_a_bare_command(self) -> None:
        violations, scanned = _scan()

        assert scanned > 100, f"only {scanned} modules scanned -- the sweep collapsed"
        assert not violations, (
            "A function that steers PATH and then executes a BARE command name "
            "decides which directory resolves that name:\n\n"
            + "\n".join(f"  {violation}" for violation in violations)
            + "\n\nWhen the prepended directory belongs to the tree under review, "
            "any package in it gets code execution inside the process that "
            "enforces every other guard. Pin the executable to an absolute path, "
            "or resolve it from a directory this repository controls."
        )
