#!/usr/bin/env python3
"""QA tool: pytest on the tests mapped from what changed since the merge base.

The test half of ``llm_qa.py changed`` (Plan 00463). Sub-agents run targeted QA,
and the coordinator runs the full suite once per delivery. The targeted path
has to be ONE command, or each agent invents its own subset and some invent
none.

**Every changed file is accounted for, or the run fails.** Each one maps, in
this order, to:

1. a DECLARED rule in ``changed_tests_map.yaml``: named tests, or the
   ``llm_qa.py`` tools that cover it (markdown is docs QA's, shell is
   shellcheck's). Declared beats inferred.
2. itself, when it is a test file.
3. the MIRRORED tests: ``src/<pkg>/a/b.py`` and ``scripts/a/b.py`` map to
   ``tests/unit/a/test_b.py`` and ``test_b_*.py``.
4. with no mirror, the same names anywhere under ``tests/``.
5. the tests that IMPORT it, for a module under ``src/`` or ``tests/``. A
   reach wider than ``MAX_IMPORT_SELECTION`` files is the full suite by
   another name, so it is unmapped instead.

A DELETED module maps to the tests that still name or import it, because they
are exactly the ones that now break. One nothing references is verified
rather than skipped. Anything left over is UNMAPPED, and an unmapped file
fails the run unless ``--allow-unmapped`` says the coordinator's full gate
will cover it. A run that tested nothing never reads as a pass.

"Changed" is everything that differs from the merge base with ``--base``:
committed work on the branch, uncommitted edits, and new untracked files. On
the base branch itself the merge base is HEAD and committed work vanishes, so
that is refused.

Usage:
    python scripts/qa/run_changed_tests.py [--json] [--root DIR] [--base REF]
        [--rules FILE] [--allow-unmapped]

``--base`` defaults to the local branch ``origin/HEAD`` names, then to
``origin/<it>``, then to a local ``main``.

Exit codes:
    0 - every change is accounted for and the selected tests passed
    1 - a selected test failed, the selection collected nothing, a change is
        unmapped, or nothing changed at all
    2 - operational failure (no base, no merge base, on the base branch,
        a malformed rules file, git unavailable)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess  # nosec B404 — runs git and this interpreter, argv form, no shell
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.qa.pytest_text_report import parse_pytest_text_output

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "changed_tests.json"
_TOOL_NAME: Final[str] = "changed_tests"

#: This repository's declared rules for what a name cannot map.
DEFAULT_RULES_PATH: Final[Path] = Path(__file__).resolve().parent / "changed_tests_map.yaml"

EXIT_SUCCESS: Final[int] = 0
EXIT_ISSUES: Final[int] = 1
EXIT_OPERATIONAL: Final[int] = 2

#: The base when ``origin/HEAD`` names none.
FALLBACK_BASE: Final[str] = "main"
_REMOTE_PREFIX: Final[str] = "origin/"
_ORIGIN_HEAD_REF: Final[str] = "refs/remotes/origin/HEAD"
_LOCAL_BRANCH_PREFIX: Final[str] = "refs/heads/"

_TEST_ROOT: Final[str] = "tests"
_UNIT_DIR: Final[str] = "unit"
_SOURCE_ROOT: Final[str] = "src"
_SCRIPTS_ROOT: Final[str] = "scripts"
_TEST_GLOB: Final[str] = "test_*.py"
_TEST_PREFIX: Final[str] = "test_"
_PYTHON_SUFFIX: Final[str] = ".py"
_PACKAGE_INIT_STEM: Final[str] = "__init__"

#: An import reach wider than this is the full suite by another name.
MAX_IMPORT_SELECTION: Final[int] = 40

# Mapping rules, as recorded in the report.
RULE_DECLARED: Final[str] = "declared"
RULE_SELF: Final[str] = "self"
RULE_MIRROR: Final[str] = "mirror"
RULE_NAME: Final[str] = "name"
RULE_IMPORT: Final[str] = "import"
RULE_DELETED_TEST: Final[str] = "deleted-test"
RULE_DELETED_UNREFERENCED: Final[str] = "deleted-unreferenced"
#: Not a mapping: the import reach exceeded ``MAX_IMPORT_SELECTION``.
_TOO_BROAD: Final[str] = "too-broad"

# Declared-rule keys.
_KEY_RULES: Final[str] = "rules"
_KEY_GLOB: Final[str] = "glob"
_KEY_TESTS: Final[str] = "tests"
_KEY_TOOLS: Final[str] = "tools"
_KEY_WHY: Final[str] = "why"
_RULE_KEYS: Final[frozenset[str]] = frozenset({_KEY_GLOB, _KEY_TESTS, _KEY_TOOLS, _KEY_WHY})

_OUTCOME_FAILED: Final[str] = "failed"

#: A git plumbing call is instant; this bound only stops a hung git from
#: hanging the QA run.
_GIT_TIMEOUT_SECONDS: Final[int] = 60

#: A targeted run is minutes at most. Past this the selection was not targeted.
_PYTEST_TIMEOUT_SECONDS: Final[int] = 1800

#: (exit code, stdout, stderr) and (exit code, combined output): injected in
#: tests so the selection and verdict logic run without a repository or pytest.
GitRunner = Callable[[list[str], Path], tuple[int, str, str]]
PytestRunner = Callable[[list[str], Path], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class DeclaredRule:
    """One entry of the rules file: a glob and what covers the files it matches."""

    glob: str
    tests: tuple[str, ...]
    tools: tuple[str, ...]
    why: str


@dataclass(slots=True)
class Selection:
    """What a change set maps to, and what it does not."""

    selected: list[str] = field(default_factory=list)
    mapping: list[dict[str, Any]] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    non_python: list[str] = field(default_factory=list)


def run_git(args: list[str], root: Path) -> tuple[int, str, str]:
    """Run one git command in ``root``; a failure to run is a non-zero result."""
    try:
        completed = subprocess.run(  # nosec B603 B607 — git by name, argv form, no shell
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, "", f"git {' '.join(args)} did not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
    """Run pytest on explicit paths under this interpreter."""
    try:
        completed = subprocess.run(  # nosec B603 — this interpreter, argv form, no shell
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=_PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_OPERATIONAL, f"ERROR: pytest did not run: {exc}\n"
    return completed.returncode, completed.stdout + completed.stderr


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _local_branch_exists(root: Path, name: str, git: GitRunner) -> bool:
    code, _, _ = git(["rev-parse", "--verify", "--quiet", f"{_LOCAL_BRANCH_PREFIX}{name}"], root)
    return code == 0


def resolve_base(
    root: Path, requested: str | None, *, git: GitRunner = run_git
) -> tuple[str | None, str | None]:
    """``(base, None)``, or ``(None, reason)`` when there is nothing to diff against.

    An explicit ``--base`` wins. Otherwise the branch ``origin/HEAD`` names:
    its local copy when there is one, because a worktree branches from the
    local copy, and the remote one when there is not. With no ``origin/HEAD``
    a local ``main`` is used.
    """
    if requested:
        return requested, None
    code, stdout, _ = git(["symbolic-ref", "--quiet", "--short", _ORIGIN_HEAD_REF], root)
    remote_default = stdout.strip()
    if code == 0 and remote_default:
        local = remote_default.removeprefix(_REMOTE_PREFIX)
        return (local if _local_branch_exists(root, local, git) else remote_default), None
    if _local_branch_exists(root, FALLBACK_BASE, git):
        return FALLBACK_BASE, None
    return None, (
        f"no default base: `origin/HEAD` is unset and there is no local `{FALLBACK_BASE}`. "
        "Pass --base <ref>."
    )


def current_branch(root: Path, *, git: GitRunner = run_git) -> str | None:
    """The checked-out branch name, or None for a detached HEAD."""
    code, stdout, _ = git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    name = stdout.strip()
    return name if code == 0 and name else None


def changed_files(
    root: Path, base: str, *, git: GitRunner = run_git
) -> tuple[list[str] | None, str | None]:
    """``(files, None)``, or ``(None, reason)`` when the change set is unknowable.

    No merge base is an ERROR, not an empty change set: an empty list would
    read as "nothing changed". Renames are listed as both paths, so a module
    renamed away still counts as deleted.
    """
    code, stdout, stderr = git(["merge-base", "HEAD", base], root)
    merge_base = stdout.strip()
    if code != 0 or not merge_base:
        detail = stderr.strip() or "no output"
        return None, f"no merge base between HEAD and `{base}`: {detail}"

    code, diffed, stderr = git(["diff", "--name-only", "--no-renames", merge_base], root)
    if code != 0:
        return None, f"git diff against {merge_base} failed: {stderr.strip() or 'no output'}"

    code, untracked, stderr = git(["ls-files", "--others", "--exclude-standard"], root)
    if code != 0:
        return None, f"git ls-files failed: {stderr.strip() or 'no output'}"

    return sorted(set(_lines(diffed)) | set(_lines(untracked))), None


def _text_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        return None
    return tuple(v.strip() for v in value)


def parse_declared_rules(raw: object) -> tuple[list[DeclaredRule], list[str]]:
    """Validate the rules file's content; a malformed entry is reported, never guessed."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get(_KEY_RULES), list):
        return [], [f"the rules file must be a mapping with a `{_KEY_RULES}` list"]
    rules: list[DeclaredRule] = []
    problems: list[str] = []
    for position, entry in enumerate(raw[_KEY_RULES], start=1):
        if not isinstance(entry, Mapping):
            problems.append(f"rule {position}: expected a mapping")
            continue
        unknown = sorted(str(key) for key in entry if key not in _RULE_KEYS)
        glob, why = entry.get(_KEY_GLOB), entry.get(_KEY_WHY)
        tests = _text_list(entry.get(_KEY_TESTS, []))
        tools = _text_list(entry.get(_KEY_TOOLS, []))
        if unknown:
            problems.append(f"rule {position}: unknown key(s) {', '.join(unknown)}")
        elif not isinstance(glob, str) or not glob.strip():
            problems.append(f"rule {position}: `{_KEY_GLOB}` must be a non-empty string")
        elif not isinstance(why, str) or not why.strip():
            problems.append(f"rule {position}: `{_KEY_WHY}` must say what covers these files")
        elif tests is None or tools is None:
            problems.append(f"rule {position}: `{_KEY_TESTS}`/`{_KEY_TOOLS}` must be string lists")
        elif bool(tests) == bool(tools):
            problems.append(
                f"rule {position}: give exactly one of `{_KEY_TESTS}` or `{_KEY_TOOLS}`"
            )
        else:
            rules.append(DeclaredRule(glob=glob.strip(), tests=tests, tools=tools, why=why.strip()))
    return rules, problems


def load_declared_rules(path: Path) -> tuple[list[DeclaredRule], list[str]]:
    """Read and validate a rules file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], [f"cannot read {path}: {exc}"]
    return parse_declared_rules(raw)


def build_test_index(root: Path) -> dict[str, list[str]]:
    """Every test file under ``tests/``, keyed by filename."""
    index: dict[str, list[str]] = {}
    test_root = root / _TEST_ROOT
    if not test_root.is_dir():
        return index
    for path in sorted(test_root.rglob(_TEST_GLOB)):
        index.setdefault(path.name, []).append(path.relative_to(root).as_posix())
    return index


def _named(stem: str, filename: str) -> bool:
    """``test_<stem>.py`` or a ``test_<stem>_*.py`` variant."""
    return filename == f"{_TEST_PREFIX}{stem}{_PYTHON_SUFFIX}" or filename.startswith(
        f"{_TEST_PREFIX}{stem}_"
    )


def _mirror_dir(path: Path) -> str | None:
    """``tests/unit/<dirs>`` for a module under ``src/<pkg>/`` or ``scripts/``."""
    parts = path.parts
    if len(parts) > 2 and parts[0] == _SOURCE_ROOT:
        return Path(_TEST_ROOT, _UNIT_DIR, *parts[2:-1]).as_posix()
    if len(parts) > 1 and parts[0] == _SCRIPTS_ROOT:
        return Path(_TEST_ROOT, _UNIT_DIR, *parts[1:-1]).as_posix()
    return None


def _dotted_name(path: Path) -> str | None:
    """The import name of a module under ``src/`` or ``tests/``, or None."""
    parts = list(path.with_suffix("").parts)
    if parts[0] == _SOURCE_ROOT:
        parts = parts[1:]
    elif parts[0] != _TEST_ROOT:
        return None
    if parts and parts[-1] == _PACKAGE_INIT_STEM:
        parts = parts[:-1]
    return ".".join(parts) or None


def _importers(dotted: str, sources: Mapping[str, str]) -> list[str]:
    """Test files that import ``dotted`` (or anything below it)."""
    direct = re.compile(rf"(?<![\w.]){re.escape(dotted)}(?!\w)")
    parent, _, leaf = dotted.rpartition(".")
    from_import = (
        re.compile(rf"from\s+{re.escape(parent)}\s+import\s+(\([^)]*\)|[^\n]*)") if parent else None
    )
    leaf_word = re.compile(rf"\b{re.escape(leaf)}\b")
    found: list[str] = []
    for test_path, text in sources.items():
        if direct.search(text) or (
            from_import is not None
            and any(leaf_word.search(match.group(1)) for match in from_import.finditer(text))
        ):
            found.append(test_path)
    return sorted(found)


def _load_sources(root: Path, index: Mapping[str, list[str]]) -> dict[str, str]:
    """Every indexed test file's text. An unreadable test file is a broken tree: it raises."""
    return {
        test_path: (root / test_path).read_text(encoding="utf-8")
        for paths in index.values()
        for test_path in paths
    }


def _python_tests(
    relative: str,
    index: Mapping[str, list[str]],
    sources: Mapping[str, str],
) -> tuple[str | None, list[str]]:
    """``(rule, tests)`` for a Python file, or ``(None, [])`` when nothing maps."""
    path = Path(relative)
    if path.stem != _PACKAGE_INIT_STEM:
        mirror = _mirror_dir(path)
        if mirror is not None:
            in_mirror = [
                test_path
                for filename, test_paths in index.items()
                if _named(path.stem, filename)
                for test_path in test_paths
                if Path(test_path).parent.as_posix() == mirror
            ]
            if in_mirror:
                return RULE_MIRROR, sorted(in_mirror)
        if path.parts[0] != _TEST_ROOT:
            anywhere = [
                test_path
                for filename, test_paths in index.items()
                if _named(path.stem, filename)
                for test_path in test_paths
            ]
            if anywhere:
                return RULE_NAME, sorted(anywhere)

    dotted = _dotted_name(path)
    if dotted is None:
        return None, []
    importers = [test for test in _importers(dotted, sources) if test != relative]
    if len(importers) > MAX_IMPORT_SELECTION:
        return _TOO_BROAD, []
    if importers:
        return RULE_IMPORT, importers
    return None, []


def select_tests(
    changed: list[str],
    index: dict[str, list[str]],
    root: Path,
    rules: list[DeclaredRule],
) -> Selection:
    """Account for every changed file: tests, a declared rule, or unmapped."""
    selection = Selection()
    selected: set[str] = set()
    sources: dict[str, str] | None = None

    for relative in changed:
        path = Path(relative)
        exists = (root / path).is_file()
        if not exists:
            selection.deleted.append(relative)
        if path.suffix != _PYTHON_SUFFIX:
            selection.non_python.append(relative)

        rule = next((r for r in rules if fnmatch.fnmatch(relative, r.glob)), None)
        if rule is not None:
            selected.update(rule.tests)
            selection.mapping.append(
                {
                    "file": relative,
                    "rule": RULE_DECLARED,
                    "tests": list(rule.tests),
                    "tools": list(rule.tools),
                }
            )
            continue

        if path.suffix != _PYTHON_SUFFIX:
            selection.unmapped.append(relative)
            continue

        is_test = path.parts[0] == _TEST_ROOT and path.name.startswith(_TEST_PREFIX)
        if is_test:
            rule_name = RULE_SELF if exists else RULE_DELETED_TEST
            tests = [relative] if exists else []
        else:
            if sources is None:
                sources = _load_sources(root, index)
            found_rule, tests = _python_tests(relative, index, sources)
            if found_rule is None and not exists and _dotted_name(path) is not None:
                found_rule = RULE_DELETED_UNREFERENCED
            if found_rule is None or found_rule == _TOO_BROAD:
                selection.unmapped.append(relative)
                continue
            rule_name = found_rule

        selected.update(tests)
        selection.mapping.append({"file": relative, "rule": rule_name, "tests": tests})

    selection.selected = sorted(selected)
    return selection


def build_report(
    *,
    base: str,
    changed: list[str],
    selection: Selection,
    exit_code: int | None,
    output: str,
    allow_unmapped: bool,
) -> dict[str, Any]:
    """The QA artefact for one targeted run.

    Passing needs every file accounted for (or the allowance given) AND, when
    tests were selected, a green run that collected some.
    """
    parsed = parse_pytest_text_output(output)
    tests_green = not selection.selected or (
        exit_code == EXIT_SUCCESS
        and parsed["failed"] == 0
        and parsed["errors"] == 0
        and parsed["total"] > 0
    )
    accounted = allow_unmapped or not selection.unmapped
    return {
        "tool": _TOOL_NAME,
        "base": base,
        "summary": {
            "passed_all": tests_green and accounted,
            "total": parsed["total"],
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
            "errors": parsed["errors"],
            "files_considered": len(changed),
            "test_files_selected": len(selection.selected),
            "unmapped": len(selection.unmapped),
        },
        "selected": selection.selected,
        "mapping": selection.mapping,
        "unmapped": selection.unmapped,
        "unmapped_allowed": allow_unmapped,
        "deleted": selection.deleted,
        "non_python": selection.non_python,
        "tests": [
            {"name": node_id, "outcome": _OUTCOME_FAILED} for node_id in parsed["failed_tests"]
        ],
    }


def failure_report(message: str) -> dict[str, Any]:
    """A report for a run that produced no verdict. Never a pass."""
    return {
        "tool": _TOOL_NAME,
        "summary": {
            "passed_all": False,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "error": message,
        },
        "selected": [],
        "unmapped": [],
        "tests": [],
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tests mapped from changed files.")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root")
    parser.add_argument("--base", default=None, help="ref to diff against (merge base)")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="declared rules file")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="pass with unmapped files; the coordinator's full gate must cover them",
    )
    parser.add_argument("--json", action="store_true", help="write the JSON artefact")
    return parser.parse_args(argv)


def _write_report(root: Path, report: dict[str, Any]) -> None:
    output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(report, indent=2), encoding="utf-8")


def _verdict(
    args: argparse.Namespace, root: Path, run_git: GitRunner, run_pytest: PytestRunner
) -> tuple[dict[str, Any], int]:
    base, error = resolve_base(root, args.base, git=run_git)
    if base is None:
        return failure_report(error or "no base to diff against"), EXIT_OPERATIONAL
    if current_branch(root, git=run_git) == base:
        return (
            failure_report(
                f"HEAD is on `{base}`, the base itself: the merge base is HEAD, so "
                "committed work cannot be told apart. Run from the worktree branch, "
                "or pass --base <ref>."
            ),
            EXIT_OPERATIONAL,
        )

    changed, error = changed_files(root, base, git=run_git)
    if changed is None:
        return failure_report(error or "the change set could not be read"), EXIT_OPERATIONAL
    if not changed:
        return (
            failure_report(f"nothing changed since the merge base with `{base}`: nothing verified"),
            EXIT_ISSUES,
        )

    rules, problems = load_declared_rules(Path(args.rules))
    if problems:
        return failure_report("; ".join(problems)), EXIT_OPERATIONAL

    selection = select_tests(changed, build_test_index(root), root, rules)
    exit_code, output = run_pytest(selection.selected, root) if selection.selected else (None, "")
    report = build_report(
        base=base,
        changed=changed,
        selection=selection,
        exit_code=exit_code,
        output=output,
        allow_unmapped=bool(args.allow_unmapped),
    )
    return report, EXIT_SUCCESS if report["summary"]["passed_all"] else EXIT_ISSUES


def _describe(report: dict[str, Any]) -> str:
    summary = report["summary"]
    unmapped = report["unmapped"]
    scope = (
        f"{summary['files_considered']} changed files: {len(unmapped)} unmapped, "
        f"{len(report['deleted'])} deleted, {len(report['non_python'])} non-Python"
    )
    if summary["test_files_selected"]:
        line = (
            f"{summary['passed']} passed, {summary['failed']} failed from "
            f"{summary['test_files_selected']} test files ({scope})"
        )
    else:
        line = f"no tests ran ({scope})"
    if unmapped:
        verdict = "ALLOWED" if report["unmapped_allowed"] else "FAILS the run"
        line += f"\nunmapped ({verdict}): " + ", ".join(unmapped)
    return line


def main(
    argv: list[str] | None = None,
    *,
    run_git: GitRunner = run_git,
    run_pytest: PytestRunner = run_pytest,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    report, verdict = _verdict(args, root, run_git, run_pytest)

    if args.json:
        _write_report(root, report)

    error = report["summary"].get("error")
    if error:
        print(f"{_TOOL_NAME}: FAILED — {error}", file=sys.stderr)
    else:
        print(f"{_TOOL_NAME}: {_describe(report)}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
