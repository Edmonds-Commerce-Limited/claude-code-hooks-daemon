"""argv is a LIST, never a string that was interpolated then split (Plan 00412).

Class 7, `interpolation-into-another-language`: a value is substituted into a
string that another language will parse, and the substitution does not survive
that parse as one token. Here the other language is argv. A command template
carries a `{file}` placeholder, the path is substituted in, and the result is
`.split()` — so anything in the PATH that looks like a separator becomes
structure in the command.

Two failures from the one line, both demonstrated by running it rather than
reading it:

    "ruff check {file}" + "/repo/my file.py"
        -> ['ruff', 'check', '/repo/my', 'file.py']

An ordinary filename with a space silently lints two paths that do not exist.
That is the boring half.

    "ruff check {file}" + "/repo/x.py --config /tmp/attacker.toml"
        -> ['ruff', 'check', '/repo/x.py', '--config', '/tmp/attacker.toml']

A FILENAME becomes an argument. `lint_on_edit` runs automatically on every
Write and filenames are agent-controlled, so this is a live route to making a
linter load a config of someone else's choosing. No shell is involved and
`shell=True` is nowhere near it — the injection is into argv, which is why a
command-injection rule looking for shells does not see it.

The fix is not escaping. It is never building argv as a string: split the
TEMPLATE, then substitute the path as a single element, so the path cannot
become two.

**What this guard does not catch.** It knows one spelling — a name assigned
from `.replace(...)` and later `.split()`, or the two chained. An argv assembled
through an f-string, `%`, `.format()`, or `shlex.split` of an interpolated value
is the same defect and is invisible here. The sweep that motivated it found
2 such sites against 35 bare `.split()` calls in `src/`, so the shape is narrow
and precise rather than complete; a broader rule would need taint tracking,
which this deliberately shallow AST subset does not do.

The sibling instance in the same class — `remote_docs/capture.py` building YAML
frontmatter by interpolation — is NOT covered by this guard either. Its target
language is YAML, not argv, and it is fixed on its own evidence rather than
implied by this rule.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

_SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "claude_code_hooks_daemon"


class _SplitArgv(NamedTuple):
    """A site building argv by splitting an interpolated string."""

    relative_path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.line} — {self.detail}"


def _names_from_replace(tree: ast.Module) -> dict[str, int]:
    """Module names bound to the result of a ``.replace(...)`` call."""
    bound: dict[str, int] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "replace"):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                bound[target.id] = node.lineno
    return bound


def _is_bare_split(call: ast.Call) -> bool:
    """``x.split()`` with no separator — the whitespace tokenisation of argv."""
    return isinstance(call.func, ast.Attribute) and call.func.attr == "split" and not call.args


def _split_argv_sites(source_root: Path) -> list[_SplitArgv]:
    """Every site that splits an interpolated string into argv."""
    found: list[_SplitArgv] = []
    for module in sorted(source_root.rglob("*.py")):
        relative = module.relative_to(source_root).as_posix()
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        replaced = _names_from_replace(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_bare_split(node)):
                continue
            base = node.func.value if isinstance(node.func, ast.Attribute) else None
            if (
                isinstance(base, ast.Call)
                and isinstance(base.func, ast.Attribute)
                and base.func.attr == "replace"
            ):
                found.append(_SplitArgv(relative, node.lineno, "chained .replace(...).split()"))
            elif isinstance(base, ast.Name) and base.id in replaced:
                found.append(
                    _SplitArgv(
                        relative,
                        node.lineno,
                        f"split() on {base.id}, assigned from .replace() at line "
                        f"{replaced[base.id]}",
                    )
                )
    return found


class TestArgvIsNeverASplitInterpolation:
    """The guard. A path with a space must not become two arguments."""

    def test_no_module_builds_argv_by_splitting(self) -> None:
        violations = _split_argv_sites(_SRC_ROOT)

        assert violations == [], (
            "These sites substitute a value into a command STRING and then split "
            "it, so a space in the value becomes an argument boundary and a flag "
            "in the value becomes a flag:\n\n  "
            + "\n  ".join(str(violation) for violation in violations)
            + "\n\nFix: split the TEMPLATE, then substitute the value as one "
            "element — `[value if part == PLACEHOLDER else part for part in "
            "template.split()]`."
        )


class TestTheScannerIsNotVacuous:
    """An empty-list assertion is what a BROKEN scanner also produces."""

    def _scan(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "offender.py").write_text(source, encoding="utf-8")
        return [site.detail for site in _split_argv_sites(tmp_path)]

    def test_a_name_assigned_from_replace_then_split_is_caught(self, tmp_path: Path) -> None:
        source = 'cmd = TEMPLATE.replace("{file}", path)\nparts = cmd.split()\n'

        assert self._scan(tmp_path, source) == [
            "split() on cmd, assigned from .replace() at line 1"
        ]

    def test_the_chained_form_is_caught(self, tmp_path: Path) -> None:
        source = 'parts = TEMPLATE.replace("{file}", path).split()\n'

        assert self._scan(tmp_path, source) == ["chained .replace(...).split()"]

    def test_the_correct_shape_is_not_flagged(self, tmp_path: Path) -> None:
        """Substituting into an already-split template is the fix, not a finding."""
        source = "parts = [path if p == PLACEHOLDER else p for p in TEMPLATE.split()]\n"

        assert self._scan(tmp_path, source) == []

    def test_an_unrelated_split_is_not_flagged(self, tmp_path: Path) -> None:
        """35 bare `.split()` calls live in src/; only interpolated ones are the defect."""
        source = 'words = some_text.split()\nlines = other.replace("a", "b")\n'

        assert self._scan(tmp_path, source) == []

    def test_a_split_with_a_separator_is_not_flagged(self, tmp_path: Path) -> None:
        """`split(",")` is parsing data, not tokenising a command line."""
        source = 'cmd = TEMPLATE.replace("{file}", path)\nparts = cmd.split(",")\n'

        assert self._scan(tmp_path, source) == []
