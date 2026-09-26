#!/usr/bin/env python3
"""Check that agent-facing messages use skill-based references.

Detects two anti-patterns in agent-facing strings:
1. Bare 'python -m claude_code_hooks_daemon' — fails because module lives in venv
2. '/hooks-daemon' slash-command syntax — Claude interprets as bash command

Correct pattern: "Use the hooks-daemon skill to restart
    (Skill tool: skill=hooks-daemon, args=restart)"

Scans: .py, .sh, .md files (excluding tests, the checker itself, and code blocks).

Usage:
    python scripts/qa/check_skill_references.py [--json] [--path DIR] [--include FILE]

Exit codes:
    0 - No violations found
    1 - Violations found
"""

import ast
import json
import re
import sys
from pathlib import Path

from claude_code_hooks_daemon.utils.claude_config import claude_config_dir
from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Claude Code's config dir holds transcripts, auto-memory and installed
# third-party plugins, never project source, wherever it is (Plan 00468
# G11): excluded by its resolved location, so an in-tree home of any name
# is skipped, not only one under a directory called `ccy`.
_CLAUDE_CONFIG_DIR = claude_config_dir().resolve()
_QA_OUTPUT_DIR = _PROJECT_ROOT / "untracked" / "qa"
_ARTEFACT_NAME = "skill_references.json"
_OUTPUT_FILE = _QA_OUTPUT_DIR / _ARTEFACT_NAME

# Files/directories to always exclude
_EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    "untracked",
    ".venv",
    "venv",
    "ccy",  # the ccy supervisor's tree, the Claude home under ccy (see _CLAUDE_CONFIG_DIR)
    "commands",
    "worktrees",
    "Completed",
    "UPGRADES",
    "RELEASES",
    "examples",
}

# Individual files to exclude (historical records, not agent-facing)
_EXCLUDED_FILES = {
    "CHANGELOG.md",
    "check_skill_references.py",
}

# Directories whose contents legitimately reference their own commands
_EXCLUDED_SELF_REFERENCING_DIRS = {
    "skills",
    "agents",
    "install",
}

# Only scan these top-level directories by default (when scanning project root)
# This focuses on agent-facing code, not historical documentation
_SCAN_DIRS = {
    "src",
    "scripts",
    ".claude",
    "init.sh",
}

# ── Patterns ──────────────────────────────────────────────────────

# Pattern 1: bare python -m claude_code_hooks_daemon (in a string context)
_BARE_PYTHON_MODULE = re.compile(r"python\s+-m\s+claude_code_hooks_daemon")

# Pattern 2: /hooks-daemon as a command (not as part of a file path)
# Matches: /hooks-daemon, /hooks-daemon restart, /hooks-daemon health
# Does NOT match: .claude/hooks-daemon/, /hooks-daemon/ (directory paths)
_SLASH_COMMAND = re.compile(r"(?<![.\w/])\/hooks-daemon(?!\s*/|/)")


# ── Violation dataclass ───────────────────────────────────────────


class _Violation:
    __slots__ = ("file", "line", "message", "rule")

    def __init__(self, file: str, line: int, rule: str, message: str) -> None:
        self.file = file
        self.line = line
        self.rule = rule
        self.message = message

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
        }


# ── Python scanner (AST-based) ───────────────────────────────────


class _PythonStringVisitor(ast.NodeVisitor):
    """Visit string literals in Python AST and check for violations."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[_Violation] = []
        self._in_docstring = False

    def visit_Module(self, node: ast.Module) -> None:
        self._skip_docstring(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._skip_docstring(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._skip_docstring(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Spelled out rather than aliased to visit_FunctionDef: the two node
        # types are unrelated to a type checker, so the alias silently declared
        # a method whose signature contradicted the base class.
        self._skip_docstring(node)
        self.generic_visit(node)

    def _skip_docstring(self, node: ast.AST) -> None:
        """Mark docstring nodes so they're skipped during checking."""
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            # Tag the docstring node's line so we skip it
            self._docstring_lines: set[int] = getattr(self, "_docstring_lines", set())
            self._docstring_lines.add(body[0].value.lineno)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            docstring_lines: set[int] = getattr(self, "_docstring_lines", set())
            if node.lineno not in docstring_lines:
                self._check_string(node.value, node.lineno)
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        # f-strings: check the string parts
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                self._check_string(value.value, node.lineno)
        self.generic_visit(node)

    def _check_string(self, value: str, lineno: int) -> None:
        # Skip CLI usage strings (developer-facing, not agent-facing)
        if value.lstrip().startswith("Usage:"):
            return
        if _BARE_PYTHON_MODULE.search(value):
            self.violations.append(
                _Violation(
                    file=str(self.filepath),
                    line=lineno,
                    rule="bare-python-module",
                    message=(
                        "Agent-facing string contains 'python -m claude_code_hooks_daemon'. "
                        "Use: 'Use the hooks-daemon skill to ... "
                        "(Skill tool: skill=hooks-daemon, args=...)'"
                    ),
                )
            )
        if _SLASH_COMMAND.search(value):
            self.violations.append(
                _Violation(
                    file=str(self.filepath),
                    line=lineno,
                    rule="slash-command-syntax",
                    message=(
                        "Agent-facing string contains '/hooks-daemon' slash syntax. "
                        "Claude interprets this as a bash command. "
                        "Use: 'Use the hooks-daemon skill to ... "
                        "(Skill tool: skill=hooks-daemon, args=...)'"
                    ),
                )
            )


def _scan_python(filepath: Path) -> list[_Violation]:
    """Scan a Python file using AST for string-literal violations."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    visitor = _PythonStringVisitor(filepath)
    visitor.visit(tree)
    return visitor.violations


# ── Bash scanner (line-based) ─────────────────────────────────────


def _scan_bash(filepath: Path) -> list[_Violation]:
    """Scan a bash script for violations in string contexts (not comments)."""
    violations: list[_Violation] = []
    try:
        lines = filepath.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        # Check for patterns in the line (likely in echo/printf strings)
        if _BARE_PYTHON_MODULE.search(line):
            violations.append(
                _Violation(
                    file=str(filepath),
                    line=lineno,
                    rule="bare-python-module",
                    message=(
                        "Bash string contains 'python -m claude_code_hooks_daemon'. "
                        "Use skill-based reference instead."
                    ),
                )
            )
        if _SLASH_COMMAND.search(line):
            violations.append(
                _Violation(
                    file=str(filepath),
                    line=lineno,
                    rule="slash-command-syntax",
                    message=(
                        "Bash string contains '/hooks-daemon' slash syntax. "
                        "Use skill-based reference instead."
                    ),
                )
            )
    return violations


# ── Markdown scanner (line-based, skip code blocks) ──────────────


def _scan_markdown(filepath: Path) -> list[_Violation]:
    """Scan markdown for violations outside of code blocks."""
    violations: list[_Violation] = []
    try:
        lines = filepath.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []

    in_code_block = False
    for lineno, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _BARE_PYTHON_MODULE.search(line):
            violations.append(
                _Violation(
                    file=str(filepath),
                    line=lineno,
                    rule="bare-python-module",
                    message=(
                        "Markdown contains 'python -m claude_code_hooks_daemon' "
                        "outside code block. Use skill-based reference."
                    ),
                )
            )
        if _SLASH_COMMAND.search(line):
            violations.append(
                _Violation(
                    file=str(filepath),
                    line=lineno,
                    rule="slash-command-syntax",
                    message=(
                        "Markdown contains '/hooks-daemon' slash syntax "
                        "outside code block. Use skill-based reference."
                    ),
                )
            )
    return violations


# ── File discovery ────────────────────────────────────────────────


def _should_exclude(path: Path, root: Path, include_filter: str | None = None) -> bool:
    """Check if a file should be excluded from scanning.

    Directory names are matched below ``root`` only (00466 N26): an agent
    worktree lives under ``untracked/worktrees/``, so matching the absolute
    path excluded every file and the check passed on nothing.
    """
    parts = relative_parts(path, root)
    # Exclude by directory
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return True

    if path.resolve().is_relative_to(_CLAUDE_CONFIG_DIR):
        return True

    # Exclude test files
    if path.name.startswith("test_"):
        return True

    # Exclude specific files
    if path.name in _EXCLUDED_FILES:
        return True

    # Exclude self-referencing directories (skills, agents, install docs)
    for part in parts:
        if part in _EXCLUDED_SELF_REFERENCING_DIRS:
            return True

    # If include filter set, only include matching files
    if include_filter and path.name != include_filter:
        return True

    return False


_SCANNERS = {
    ".py": _scan_python,
    ".sh": _scan_bash,
    ".bash": _scan_bash,
    ".md": _scan_markdown,
}


def _is_project_root(directory: Path) -> bool:
    return (directory / "pyproject.toml").exists() and (directory / "src").exists()


def _collect_files(directory: Path, include_filter: str | None = None) -> tuple[list[Path], int]:
    """Collect scannable files, using _SCAN_DIRS when at project root.

    Returns:
        The files to scan, and how many candidates were found before the
        exclusions, so a scan that excluded everything can say so.
    """
    files: list[Path] = []

    if _is_project_root(directory):
        # At project root: scan focused directories + root-level files
        for scan_entry in _SCAN_DIRS:
            target = directory / scan_entry
            if target.is_file():
                files.append(target)
            elif target.is_dir():
                for ext in _SCANNERS:
                    files.extend(walk_files(target, f"*{ext}"))
        # Also scan root-level CLAUDE.md, README.md
        for root_file in directory.glob("*.md"):
            files.append(root_file)
    else:
        # Custom path: scan everything
        for ext in _SCANNERS:
            files.extend(walk_files(directory, f"*{ext}"))

    candidates = [f for f in files if not f.is_symlink() and f.suffix in _SCANNERS]
    kept = [f for f in candidates if not _should_exclude(f, directory, include_filter)]
    return kept, len(candidates)


def scan_directory(
    directory: Path,
    include_filter: str | None = None,
) -> tuple[list[_Violation], int, int]:
    """Scan a directory for skill-reference violations.

    Returns:
        The violations found, the count of files actually scanned — the
        denominator that tells a genuinely clean sweep apart from one that
        silently scanned nothing — and the candidate count before exclusions.
    """
    violations: list[_Violation] = []
    files_scanned = 0

    files, candidates = _collect_files(directory, include_filter)
    for filepath in files:
        scanner = _SCANNERS[filepath.suffix]
        try:
            violations.extend(scanner(filepath))
        except OSError as exc:
            # One unreadable file must not abort the sweep, and must not read
            # as a clean one either (00466 N21): it is a finding of its own.
            violations.append(
                _Violation(
                    str(filepath),
                    0,
                    "unreadable-file",
                    f"could not be read, so it was never checked: {exc}",
                )
            )
        else:
            files_scanned += 1

    violations.sort(key=lambda v: (v.file, v.line))
    return violations, files_scanned, candidates


# ── Main ──────────────────────────────────────────────────────────


def main() -> int:
    json_mode = "--json" in sys.argv
    scan_path = _PROJECT_ROOT
    include_filter: str | None = None

    # Parse args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            scan_path = Path(args[i + 1]).resolve()
            i += 2
        elif args[i] == "--include" and i + 1 < len(args):
            include_filter = args[i + 1]
            i += 2
        elif args[i] == "--json":
            i += 1
        else:
            i += 1

    violations, files_scanned, candidates = scan_directory(scan_path, include_filter)
    vacuous = vacuous_scan_failure(
        examined=files_scanned, candidates=candidates, noun="files", root=scan_path
    )

    output = {
        "tool": "skill_references",
        "summary": {
            "passed": len(violations) == 0 and vacuous is None,
            "vacuous_scan": vacuous,
            "total_violations": len(violations),
            "by_rule": {
                "bare-python-module": sum(1 for v in violations if v.rule == "bare-python-module"),
                "slash-command-syntax": sum(
                    1 for v in violations if v.rule == "slash-command-syntax"
                ),
            },
            "files_scanned": files_scanned,
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        # A --path scan answers "is this DIRECTORY clean", which is not the
        # question the repository artefact answers. llm_qa publishes that
        # artefact as this check's evidence surface, so a scoped run reports
        # beside what it scanned rather than overwriting it.
        output_file = scan_path / _ARTEFACT_NAME if scan_path != _PROJECT_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))
        if vacuous is not None:
            print(f"FAILED: {vacuous}")
        elif violations:
            print(f"Found {len(violations)} skill-reference violations")
            for v in violations:
                print(f"  {v.file}:{v.line}: [{v.rule}] {v.message}")
        else:
            print(f"No skill-reference violations found ({files_scanned} files scanned)")
    else:
        if vacuous is not None:
            print(f"FAILED: {vacuous}")
        elif violations:
            print(f"Found {len(violations)} skill-reference violations:\n")
            for v in violations:
                print(f"  {v.file}:{v.line}")
                print(f"    [{v.rule}] {v.message}")
                print()
        else:
            print(f"No skill-reference violations found ({files_scanned} files scanned)")

    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
