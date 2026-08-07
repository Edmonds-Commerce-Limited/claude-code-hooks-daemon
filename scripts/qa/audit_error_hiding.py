#!/usr/bin/env python3
"""Audit codebase for error hiding patterns that violate FAIL FAST principles.

This script uses AST analysis to detect patterns like:
- Silent try/except/pass
- Silent try/except/continue
- Returning None on errors (instead of raising)
- Warning instead of error in critical paths
- Empty except blocks with just logging
- A single-statement handler that assigns a fallback value with no logging
  and no re-raise ("silent-fallback")

Scope (Plan 00200 Phase 5): this auditor originally scanned ``src/`` only,
commented "production code only" — which left the QA scripts that IMPLEMENT
the gates permanently exempt from the gate they enforce. That is how the
``run_lint.sh`` ``JSONDecodeError`` swallow (fixed in ``fad60fa6``) went
undetected: it lived in ``scripts/``, not ``src/``, AND inside Python
embedded in a ``.sh`` heredoc, AND its shape (bare assignment, not
pass/continue/log) had no matching rule. All three gaps are closed here —
see ``AUDITED_DIRECTORIES``, ``AUDITED_ROOT_FILES``,
``extract_heredoc_python_blocks``, and the ``silent-fallback`` rule below.

Usage:
    python scripts/qa/audit_error_hiding.py [--fix]

Exit codes:
    0 - No violations found
    1 - Violations found (or other error)
"""

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingStrategy
from claude_code_hooks_daemon.strategies.error_hiding.shell_strategy import (
    ShellErrorHidingStrategy,
)

# Violation types
VIOLATION_TYPES = {
    "silent-pass": "Silent try/except/pass - error is completely ignored",
    "silent-continue": "Silent try/except/continue - error skipped in loop",
    "return-none-on-error": "Returns None on error instead of raising",
    "log-and-continue": "Logs error but continues execution",
    "bare-except": "Bare except clause without specific exception type",
    "warning-instead-of-error": "Uses logger.warning() for critical failures",
    "silent-fallback": (
        "Exception handler assigns a fallback value with no logging or "
        "re-raise - failure becomes indistinguishable from success"
    ),
}

# Directories audited recursively for BOTH Python (*.py) and shell (*.sh,
# *.bash) error-hiding patterns. Widened beyond "src" in Plan 00200 Phase 5:
# the QA scripts that implement the gates must themselves be in scope.
AUDITED_DIRECTORIES: tuple[str, ...] = ("src", "scripts")

# Root-level files (not inside an AUDITED_DIRECTORIES tree) audited
# individually. install.py is the installer entry point; the *.sh scripts
# are the actual bootstrap/wrapper scripts a client's shell executes.
# (The root test_*.sh scripts formerly listed here were removed from the
# repo as part of a concurrent repo-hygiene pass; is_file() below already
# skips missing entries, but there is no reason to keep dead references.)
AUDITED_ROOT_FILES: tuple[str, ...] = (
    "install.py",
    "daemon.sh",
    "init.sh",
    "install.sh",
)

_DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "untracked/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".git/",
    "build/",
    "dist/",
    ".eggs/",
)

_SHELL_EXTENSIONS: tuple[str, ...] = (".sh", ".bash")

# Matches a heredoc start line invoking python (python/python3, or a shell
# variable whose name contains PYTHON, e.g. ${VENV_PYTHON}, ${PYTHON_BIN}).
# Group 1: "-" for the tab-stripping <<- form, else "".
# Group 2: the (optional) quote character wrapping the delimiter.
# Group 3: the heredoc delimiter itself.
# Deliberately NOT anchored to end-of-line: a redirect commonly trails the
# delimiter on the same line (e.g. `python3 << 'EOF' > "${OUTPUT_FILE}"`).
_PYTHON_HEREDOC_START_RE = re.compile(
    r"(?:\bpython3?\b|\$\{\w*PYTHON\w*\})[^\n]*?<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2"
)

# Best-effort bash function boundary detector, used only to populate the
# "function" field on shell-pattern violations for drift-proof exclusion
# matching (mirrors this project's `name() {` / `}` at column 0 convention,
# see scripts/venv-include.bash). Falls back to None (module-level) when the
# convention isn't followed — exclusions.json's "lines" matching covers that.
_BASH_FUNCTION_START_RE = re.compile(r"^([A-Za-z_]\w*)\s*\(\)\s*\{?\s*$")


class ErrorHidingVisitor(ast.NodeVisitor):
    """AST visitor to detect error hiding patterns."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[dict[str, Any]] = []
        self._seen: set[tuple[str, int, str]] = set()
        self.in_test_file = "test_" in filepath.name or filepath.parts[-2] == "tests"
        self._function_stack: list[str] = []

    def visit_Try(self, node: ast.Try) -> None:
        """Check try/except blocks for error hiding."""
        for handler in node.handlers:
            # Check for bare except (no exception type)
            if handler.type is None and not self.in_test_file:
                self._add_violation(
                    node,
                    "bare-except",
                    "Bare except clause - specify exception type",
                )

            # Check handler body for violations
            if len(handler.body) == 1:
                stmt = handler.body[0]

                # Pattern: try/except/pass
                if isinstance(stmt, ast.Pass):
                    self._add_violation(
                        node,
                        "silent-pass",
                        "Exception silently discarded with pass",
                    )

                # Pattern: try/except/continue
                elif isinstance(stmt, ast.Continue):
                    self._add_violation(
                        node,
                        "silent-continue",
                        "Exception silently skipped with continue",
                    )

                # Pattern: try/except/<bare assignment> - the exception is
                # replaced by a fallback value with no logging and no
                # re-raise, so the caller can never distinguish "clean run"
                # from "the check that produced this value never ran".
                # This is the exact shape of the run_lint.sh JSONDecodeError
                # swallow that motivated Plan 00200.
                elif isinstance(stmt, ast.Assign):
                    self._add_violation(
                        node,
                        "silent-fallback",
                        "Exception handler assigns a fallback value with no "
                        "logging or re-raise - failure becomes indistinguishable "
                        "from success",
                    )

            # Check for log-and-continue pattern
            if self._is_log_and_continue(handler):
                self._add_violation(
                    node,
                    "log-and-continue",
                    "Logs error but continues execution",
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for return-none-on-error pattern."""
        self._function_stack.append(node.name)
        # Look for try/except that returns None
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                for handler in child.handlers:
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Return):
                            # Check if returning None
                            if stmt.value is None or (
                                isinstance(stmt.value, ast.Constant)
                                and stmt.value.value is None
                            ):
                                self._add_violation(
                                    child,
                                    "return-none-on-error",
                                    "Returns None on error instead of raising",
                                )

        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Delegate to visit_FunctionDef for async functions."""
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def _is_log_and_continue(self, handler: ast.ExceptHandler) -> bool:
        """Check if handler just logs and continues."""
        # Pattern: except: logger.error(...) with no raise
        if len(handler.body) == 1:
            stmt = handler.body[0]
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if isinstance(func, ast.Attribute):
                    # Check for logger.error(), logger.warning()
                    if func.attr in ("error", "warning", "info", "debug"):
                        return True
        return False

    def _add_violation(self, node: ast.AST, rule: str, message: str) -> None:
        """Add a violation to the list, deduplicating by (file, line, rule)."""
        line: int = getattr(node, "lineno", 0)
        key = (str(self.filepath), line, rule)
        if key in self._seen:
            return
        self._seen.add(key)
        self.violations.append(
            {
                "file": str(self.filepath),
                "line": line,
                "function": self._function_stack[-1] if self._function_stack else None,
                "rule": rule,
                "message": message,
                "description": VIOLATION_TYPES.get(rule, "Unknown violation"),
            }
        )


def audit_file(filepath: Path) -> list[dict[str, Any]]:
    """Audit a single Python file for error hiding patterns."""
    try:
        with open(filepath, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        visitor = ErrorHidingVisitor(filepath)
        visitor.visit(tree)
        return visitor.violations

    except SyntaxError:
        # Skip files with syntax errors
        return []
    except Exception as e:
        print(f"Error auditing {filepath}: {e}", file=sys.stderr)
        return []


def audit_directory(
    directory: Path, exclude_patterns: tuple[str, ...] = _DEFAULT_EXCLUDE_PATTERNS
) -> list[dict[str, Any]]:
    """Audit all Python files in a directory."""
    all_violations = []

    for py_file in directory.rglob("*.py"):
        # Skip excluded paths
        if any(pattern in str(py_file) for pattern in exclude_patterns):
            continue

        violations = audit_file(py_file)
        all_violations.extend(violations)

    return all_violations


def extract_heredoc_python_blocks(content: str) -> list[tuple[int, str]]:
    """Find python-invocation heredocs in shell source; return their bodies.

    Each result is ``(body_start_line, source)`` where ``body_start_line`` is
    the 1-based line number of the FIRST line of the heredoc body within
    ``content`` — callers use it to offset AST line numbers back onto the
    original file (see ``audit_heredoc_python``).

    Only heredocs whose start line invokes python (``python``/``python3``, or
    a shell variable containing ``PYTHON`` such as ``${VENV_PYTHON}``) are
    extracted. A heredoc feeding some other command (``cat <<EOF``, or a
    ``while read ... done <<EOF`` loop) is left alone.
    """
    lines = content.splitlines()
    blocks: list[tuple[int, str]] = []
    total = len(lines)
    i = 0
    while i < total:
        match = _PYTHON_HEREDOC_START_RE.search(lines[i])
        if match is None:
            i += 1
            continue

        strip_leading_whitespace = match.group(1) == "-"
        delimiter = match.group(3)

        body_start_index = i + 1  # 0-based index of the first body line
        body_lines: list[str] = []
        j = body_start_index
        terminated = False
        while j < total:
            candidate = lines[j].strip() if strip_leading_whitespace else lines[j]
            if candidate == delimiter:
                terminated = True
                break
            body_lines.append(lines[j])
            j += 1

        if terminated:
            blocks.append((body_start_index + 1, "\n".join(body_lines)))
            i = j + 1
        else:
            # Unterminated heredoc (e.g. a truncated/malformed file) — there
            # is nothing coherent to audit; move past the start line only.
            i += 1

    return blocks


def audit_heredoc_python(filepath: Path) -> list[dict[str, Any]]:
    """Extract and audit Python embedded in shell heredocs (Plan 00200 Phase 5).

    This closes the exact hiding place of the ``run_lint.sh``
    ``JSONDecodeError`` swallow that motivated this plan: Python logic living
    inside a ``python3 << 'EOF'`` heredoc in a ``.sh`` file was invisible to
    the ``*.py``-only auditor twice over (wrong file extension, wrong
    directory). Violations are reported against the ORIGINAL ``.sh`` file
    with line numbers offset onto the real file, not the extracted fragment.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not read {filepath}: {exc}") from exc

    violations: list[dict[str, Any]] = []
    for body_start_line, source in extract_heredoc_python_blocks(content):
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            # Unquoted heredocs allow shell ${VAR} interpolation inside the
            # body, which is not valid Python until the shell expands it.
            # Skip rather than false-positive on an unparseable fragment —
            # audit_file() already treats a genuine SyntaxError the same way.
            continue
        ast.increment_lineno(tree, body_start_line - 1)
        visitor = ErrorHidingVisitor(filepath)
        visitor.visit(tree)
        violations.extend(visitor.violations)

    return violations


def _enclosing_bash_function(content: str, line: int) -> str | None:
    """Best-effort nearest-preceding ``name() {`` for a given line number.

    Approximate by design: it does not track brace depth, relying instead on
    this project's convention of closing shell functions with a bare ``}``
    at column 0 (see scripts/venv-include.bash). Used only to populate the
    "function" field on shell-pattern violations for drift-proof exclusion
    matching; a violation with no function context lands at module level,
    which exclusions.json's "lines" matching already supports.
    """
    lines = content.splitlines()
    current: str | None = None
    for lineno in lines[: max(line - 1, 0)]:
        match = _BASH_FUNCTION_START_RE.match(lineno)
        if match:
            current = match.group(1)
        elif lineno == "}":
            current = None
    return current


def audit_shell_patterns(
    filepath: Path, strategy: ErrorHidingStrategy
) -> list[dict[str, Any]]:
    """Scan a shell file for language-level error-hiding patterns.

    Reuses ``strategy.patterns`` (Plan 00200 Phase 5 Task 5.3) instead of
    reimplementing the regex list, so the write-time ``error_hiding_blocker``
    handler and this batch auditor can never disagree about what counts as
    shell error-hiding.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not read {filepath}: {exc}") from exc

    violations: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for pattern in strategy.patterns:
        for match in re.finditer(pattern.regex, content, re.MULTILINE):
            line = content.count("\n", 0, match.start()) + 1
            rule = f"shell-{pattern.name}"
            key = (line, rule)
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                {
                    "file": str(filepath),
                    "line": line,
                    "function": _enclosing_bash_function(content, line),
                    "rule": rule,
                    "message": pattern.suggestion,
                    "description": f"Shell error-hiding pattern ({pattern.name}): {pattern.example}",
                }
            )

    return violations


def collect_shell_files(
    workspace: Path, exclude_patterns: tuple[str, ...] = _DEFAULT_EXCLUDE_PATTERNS
) -> list[Path]:
    """Gather every ``.sh`` / ``.bash`` file under the audited roots."""
    files: list[Path] = []

    for rel in AUDITED_DIRECTORIES:
        directory = workspace / rel
        if not directory.is_dir():
            continue
        for pattern in ("*.sh", "*.bash"):
            for shell_file in directory.rglob(pattern):
                if any(excl in str(shell_file) for excl in exclude_patterns):
                    continue
                files.append(shell_file)

    for rel in AUDITED_ROOT_FILES:
        candidate = workspace / rel
        if candidate.suffix in _SHELL_EXTENSIONS and candidate.is_file():
            files.append(candidate)

    return sorted(files)


def collect_python_violations(workspace: Path) -> list[dict[str, Any]]:
    """Audit every ``.py`` file under the audited roots (dirs + root files)."""
    violations: list[dict[str, Any]] = []

    for rel in AUDITED_DIRECTORIES:
        directory = workspace / rel
        if directory.is_dir():
            violations.extend(audit_directory(directory))

    for rel in AUDITED_ROOT_FILES:
        candidate = workspace / rel
        if candidate.suffix == ".py" and candidate.is_file():
            violations.extend(audit_file(candidate))

    return violations


def collect_shell_violations(workspace: Path) -> list[dict[str, Any]]:
    """Audit every shell file under the audited roots: embedded Python heredocs
    (Task 5.2) plus shell-language patterns reused from the write-time
    handler's strategy (Task 5.3)."""
    shell_strategy = ShellErrorHidingStrategy()
    violations: list[dict[str, Any]] = []

    for shell_file in collect_shell_files(workspace):
        violations.extend(audit_heredoc_python(shell_file))
        violations.extend(audit_shell_patterns(shell_file, shell_strategy))

    return violations


def format_violation_report(violations: list[dict[str, Any]]) -> str:
    """Format violations into a readable report."""
    if not violations:
        return "✅ No error hiding violations found!\n"

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = {}
    for v in violations:
        file = v["file"]
        if file not in by_file:
            by_file[file] = []
        by_file[file].append(v)

    # Build report
    lines = [f"❌ Found {len(violations)} error hiding violation(s)\n"]

    for file, file_violations in sorted(by_file.items()):
        lines.append(f"\n{file}:")
        for v in sorted(file_violations, key=lambda x: x["line"]):
            lines.append(f"  Line {v['line']}: {v['rule']}")
            lines.append(f"    {v['message']}")
            lines.append(f"    ({v['description']})")

    return "\n".join(lines)


def load_exclusions(script_dir: Path) -> list[dict[str, Any]]:
    """Load intentional-pattern exclusions from JSON file."""
    exclusions_file = script_dir / "error_hiding_exclusions.json"
    if not exclusions_file.exists():
        return []
    try:
        with open(exclusions_file, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("exclusions", [])
    except Exception as e:
        print(f"Warning: could not load exclusions file: {e}", file=sys.stderr)
        return []


def apply_exclusions(
    violations: list[dict[str, Any]], exclusions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove violations that match an intentional-pattern exclusion entry.

    Exclusions support two matching strategies:
    - ``function``: matches by enclosing function name + rule (drift-proof)
    - ``lines``: matches by line number (legacy, drifts on code edits)

    Function-based matching is preferred. Line-based is kept for backward
    compatibility and for violations at module level.
    """
    if not exclusions:
        return violations

    filtered = []
    for v in violations:
        excluded = False
        for excl in exclusions:
            file_suffix = excl.get("file", "")
            if not v["file"].endswith(file_suffix):
                continue
            excl_rule = excl.get("rule", "")
            if excl_rule and v["rule"] != excl_rule:
                continue
            # Function-based match (preferred — immune to line drift)
            if "function" in excl:
                if v.get("function") == excl["function"]:
                    excluded = True
                    break
            # Line-based match (legacy fallback)
            elif v["line"] in excl.get("lines", []):
                excluded = True
                break
        if not excluded:
            filtered.append(v)
    return filtered


def write_json_output(violations: list[dict[str, Any]], output_path: Path) -> None:
    """Write violations as JSON to output_path for QA pipeline consumption."""
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": violations,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main() -> int:
    """Main entry point."""
    workspace = Path(__file__).parent.parent.parent

    json_mode = "--json" in sys.argv

    if not json_mode:
        print("Auditing codebase for error hiding patterns...")
        print(f"Workspace: {workspace}\n")

    # Audit AUDITED_DIRECTORIES + AUDITED_ROOT_FILES (Plan 00200 Phase 5:
    # widened beyond "production code only" src/, which left the QA scripts
    # that IMPLEMENT the gates permanently exempt from the gate they enforce).
    all_violations = collect_python_violations(workspace) + collect_shell_violations(workspace)

    # Apply exclusions for intentional patterns (documented in error_hiding_exclusions.json)
    script_dir = Path(__file__).parent
    exclusions = load_exclusions(script_dir)
    all_violations = apply_exclusions(all_violations, exclusions)

    if json_mode:
        output_path = workspace / "untracked" / "qa" / "error_hiding.json"
        write_json_output(all_violations, output_path)
    else:
        # Print report
        print(format_violation_report(all_violations))

    # Summary
    if all_violations:
        if not json_mode:
            print(f"\n⚠️  Action Required: Fix {len(all_violations)} violation(s)")
            print("These patterns violate FAIL FAST principles.")
        return 1

    if not json_mode:
        print("✅ All checks passed - no error hiding detected!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
