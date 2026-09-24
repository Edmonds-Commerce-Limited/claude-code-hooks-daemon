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
from collections.abc import Iterator
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
    "return-none-via-local": (
        "Handler binds None or an empty default to a local that is returned "
        "after the try - return-none-on-error spelt so the token is not seen"
    ),
    "log-and-continue": "Logs error but continues execution",
    "bare-except": "Bare except clause without specific exception type",
    "warning-instead-of-error": "Uses logger.warning() for critical failures",
    "silent-fallback": (
        "Exception handler assigns a fallback value with no logging or "
        "re-raise - failure becomes indistinguishable from success"
    ),
    "unauditable-file": (
        "The file could not be opened or decoded, so it was never checked "
        "for error-hiding patterns - reported rather than silently skipped"
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


def _is_excluded(path: Path, root: Path, exclude_patterns: tuple[str, ...]) -> bool:
    """Is ``path`` inside one of the excluded directories of ``root``'s tree?

    The patterns name directories to skip INSIDE the tree being scanned, so
    the match is made against the path relative to that tree — never against
    the absolute path. Matching absolutely made every file invisible whenever
    the checkout itself lived under a matching directory, which is this
    project's own sanctioned worktree layout (``untracked/worktrees/<branch>``,
    see ``WORKTREE_DIR_PATTERNS``): the audit then collected nothing, reported
    no violations, and marked every live exclusion stale.

    A path outside ``root`` cannot be made relative to it, so it is judged on
    its absolute form rather than silently included.
    """
    relative = path.relative_to(root) if path.is_relative_to(root) else path
    return any(pattern in str(relative) for pattern in exclude_patterns)


_SHELL_EXTENSIONS: tuple[str, ...] = (".sh", ".bash")

# Matches a heredoc start line invoking python (python/python3, or a shell
# variable whose name contains PYTHON, e.g. ${VENV_PYTHON}, ${PYTHON_BIN}).  # python-var-guidance-exempt: describes what the regex DETECTS, not how to invoke python
# The marker above must sit on the offending line itself — the check is
# line-scoped, so a nearby explanatory comment does not exempt anything.
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


# Logger methods that report a failure where an operator will see it.
_SURFACING_LOG_LEVELS: frozenset[str] = frozenset(
    {"warning", "warn", "error", "exception", "critical", "fatal"}
)

# Empty constructors a handler substitutes for a result it could not compute.
_EMPTY_DEFAULT_CALLS: frozenset[str] = frozenset({"list", "dict", "tuple", "set", "frozenset"})


def _is_none(value: ast.expr | None) -> bool:
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def _is_fallback_value(value: ast.expr | None) -> bool:
    """None, or an empty default indistinguishable from "nothing found"."""
    if _is_none(value):
        return True
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str | bytes) and not value.value
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in _EMPTY_DEFAULT_CALLS
        and not value.args
        and not value.keywords
    )


def _walk_own_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Every node in ``node``'s body, not descending into nested scopes."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            yield from _walk_own_scope(child)


def _handler_surfaces_the_error(handler: ast.ExceptHandler) -> bool:
    for child in _walk_own_scope(handler):
        if isinstance(child, ast.Raise):
            return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _SURFACING_LOG_LEVELS
        ):
            return True
    return False


def _names_bound_to_a_fallback(handler: ast.ExceptHandler) -> set[str]:
    names: set[str] = set()
    for stmt in handler.body:
        if isinstance(stmt, ast.Assign) and _is_fallback_value(stmt.value):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
            and _is_fallback_value(stmt.value)
        ):
            names.add(stmt.target.id)
    return names


def _returns_of_a_local(scope: list[ast.AST]) -> list[tuple[str, int]]:
    """``(name, line)`` for each return that hands back a local's fallback.

    Either ``return name``, or ``return None`` / a bare ``return`` directly
    under ``if name is None:`` / ``if not name:``.
    """
    found: list[tuple[str, int]] = []
    for node in scope:
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
            found.append((node.value.id, node.lineno))
        elif isinstance(node, ast.If):
            name = _name_tested_for_emptiness(node.test)
            if name is None:
                continue
            found.extend(
                (name, stmt.lineno)
                for stmt in node.body
                if isinstance(stmt, ast.Return) and _is_none(stmt.value)
            )
    return found


def _name_tested_for_emptiness(test: ast.expr) -> str | None:
    if (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and _is_none(test.comparators[0])
    ):
        return test.left.id
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
    ):
        return test.operand.id
    return None


def _is_rebound_between(scope: list[ast.AST], name: str, after: int, before: int) -> bool:
    """Is ``name`` given a real value on a line strictly between the two?

    Binding the same kind of fallback again (an outer handler's ``x = None``)
    is not a rebinding: the value still means "the call failed".
    """
    fallback_targets = {
        id(target)
        for node in scope
        if isinstance(node, ast.Assign | ast.AnnAssign) and _is_fallback_value(node.value)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
    }
    return any(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Store)
        and id(node) not in fallback_targets
        and after < node.lineno < before
        for node in scope
    )


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
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """An async function hides errors the same ways a plain one does."""
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                for handler in child.handlers:
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Return) and _is_none(stmt.value):
                            self._add_violation(
                                child,
                                "return-none-on-error",
                                "Returns None on error instead of raising",
                            )
        self._check_fallback_returned_through_a_local(node)

        self.generic_visit(node)
        self._function_stack.pop()

    def _check_fallback_returned_through_a_local(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """00466 N29: judge the flow, not the ``return None`` token.

        A handler that binds None (or an empty default) to a local, which the
        function then returns after the ``try`` with nothing rebinding it,
        behaves exactly like ``return None`` in the handler. It is not hiding
        when the handler re-raises or says so at warning level or above.
        """
        scope = list(_walk_own_scope(node))
        returns = _returns_of_a_local(scope)
        for try_node in (stmt for stmt in scope if isinstance(stmt, ast.Try)):
            try_end: int = try_node.end_lineno or try_node.lineno
            for handler in try_node.handlers:
                if _handler_surfaces_the_error(handler):
                    continue
                for name in _names_bound_to_a_fallback(handler):
                    if any(
                        returned == name
                        and line > try_end
                        and not _is_rebound_between(scope, name, try_end, line)
                        for returned, line in returns
                    ):
                        self._add_violation(
                            handler,
                            "return-none-via-local",
                            f"Handler binds a fallback to '{name}', returned after "
                            "the try with no warning-or-above log and no re-raise",
                        )

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
    except (OSError, UnicodeDecodeError) as exc:
        # The file could not be opened or decoded at all — reported as a
        # finding rather than silently contributing zero violations, which
        # was indistinguishable from "this file is clean". A bare
        # `except Exception: print(...); return []` here used to be the
        # exact shape this auditor exists to catch, committed by the
        # auditor itself.
        return [
            {
                "file": str(filepath),
                "line": 0,
                "function": None,
                "rule": "unauditable-file",
                "message": f"Could not read {filepath} for error-hiding audit: {exc}",
                "description": VIOLATION_TYPES["unauditable-file"],
            }
        ]


def audit_directory(
    directory: Path,
    exclude_patterns: tuple[str, ...] = _DEFAULT_EXCLUDE_PATTERNS,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Audit all Python files in a directory.

    ``root`` is the tree the exclusion patterns are relative to (the
    workspace when called from :func:`collect_python_violations`); it
    defaults to ``directory`` itself. See :func:`_is_excluded`.
    """
    all_violations = []

    for py_file in collect_python_files(directory, exclude_patterns, root):
        all_violations.extend(audit_file(py_file))

    return all_violations


def collect_python_files(
    directory: Path,
    exclude_patterns: tuple[str, ...] = _DEFAULT_EXCLUDE_PATTERNS,
    root: Path | None = None,
) -> list[Path]:
    """Every non-excluded ``*.py`` file under ``directory``."""
    base = directory if root is None else root
    return sorted(
        py_file
        for py_file in directory.rglob("*.py")
        if not _is_excluded(py_file, base, exclude_patterns)
    )


def extract_heredoc_python_blocks(content: str) -> list[tuple[int, str]]:
    """Find python-invocation heredocs in shell source; return their bodies.

    Each result is ``(body_start_line, source)`` where ``body_start_line`` is
    the 1-based line number of the FIRST line of the heredoc body within
    ``content`` — callers use it to offset AST line numbers back onto the
    original file (see ``audit_heredoc_python``).

    Only heredocs whose start line invokes python (``python``/``python3``, or
    a shell variable containing ``PYTHON`` such as ``${VENV_PYTHON}``) are  python-var-guidance-exempt: the shape DETECTED, not a recommendation
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


def audit_shell_patterns(filepath: Path, strategy: ErrorHidingStrategy) -> list[dict[str, Any]]:
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
                if _is_excluded(shell_file, workspace, exclude_patterns):
                    continue
                files.append(shell_file)

    for rel in AUDITED_ROOT_FILES:
        candidate = workspace / rel
        if candidate.suffix in _SHELL_EXTENSIONS and candidate.is_file():
            files.append(candidate)

    return sorted(files)


def collect_workspace_python_files(workspace: Path) -> list[Path]:
    """Every ``.py`` file the audit covers: audited dirs + audited root files."""
    files: list[Path] = []

    for rel in AUDITED_DIRECTORIES:
        directory = workspace / rel
        if directory.is_dir():
            files.extend(collect_python_files(directory, _DEFAULT_EXCLUDE_PATTERNS, workspace))

    for rel in AUDITED_ROOT_FILES:
        candidate = workspace / rel
        if candidate.suffix == ".py" and candidate.is_file():
            files.append(candidate)

    return files


def collect_python_violations(workspace: Path) -> list[dict[str, Any]]:
    """Audit every ``.py`` file under the audited roots (dirs + root files)."""
    return [
        violation
        for py_file in collect_workspace_python_files(workspace)
        for violation in audit_file(py_file)
    ]


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
            # A stale-exclusion finding carries no description — its message
            # already says everything. Demanding one crashed the text report
            # on exactly the runs that had something to report.
            description = v.get("description")
            if description:
                lines.append(f"    ({description})")

    return "\n".join(lines)


def load_exclusions(script_dir: Path) -> list[dict[str, Any]]:
    """Load intentional-pattern exclusions from JSON file."""
    exclusions_file = script_dir / "error_hiding_exclusions.json"
    if not exclusions_file.exists():
        return []
    try:
        with open(exclusions_file, encoding="utf-8") as f:
            data = json.load(f)
        exclusions = data.get("exclusions", []) if isinstance(data, dict) else []
        # Only well-formed entries are honoured. A malformed one is dropped
        # rather than trusted, which can only make the audit STRICTER — the
        # safe direction for a check whose job is to find hidden errors.
        return [entry for entry in exclusions if isinstance(entry, dict)]
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

    return [v for v in violations if not any(_exclusion_matches(v, excl) for excl in exclusions)]


def _exclusion_matches(violation: dict[str, Any], exclusion: dict[str, Any]) -> bool:
    """Does this exclusion entry suppress this violation?

    Sole definition of the matching rule. apply_exclusions() and
    find_stale_exclusions() both call it, so "what an exclusion suppresses"
    and "what counts as an exclusion suppressing nothing" can never drift
    apart into two subtly different answers.
    """
    file_suffix = exclusion.get("file", "")
    if not violation["file"].endswith(file_suffix):
        return False
    excl_rule = exclusion.get("rule", "")
    if excl_rule and violation["rule"] != excl_rule:
        return False
    # Function-based match (preferred — immune to line drift)
    if "function" in exclusion:
        return bool(violation.get("function") == exclusion["function"])
    # Line-based match (retained for module-level and shell-script sites,
    # where there is no enclosing function to key on)
    return violation["line"] in exclusion.get("lines", [])


def find_stale_exclusions(
    violations: list[dict[str, Any]], exclusions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Exclusions that suppress nothing — reported so drift cannot stay silent.

    An exclusion is a standing licence to ignore a specific finding. When it
    stops matching, exactly two things can have happened, and they have
    opposite remedies:

    1. It DRIFTED. Line-keyed entries move out of alignment whenever code is
       inserted above them; function-keyed entries orphan when the function is
       renamed. The entry now exempts the wrong site while the real finding
       resurfaces somewhere else, which reads as a brand-new violation with no
       hint that a suppression caused it. Observed twice in one session in
       upgrade_version.sh.
    2. The underlying code was FIXED. The licence is spent and should be
       withdrawn, or it will silently cover a future re-introduction.

    Both are invisible without this check, because a suppression file is only
    ever consulted to REMOVE findings — nothing previously asked whether each
    entry still earned its place.

    Takes the UNFILTERED violation list.
    """
    stale: list[dict[str, Any]] = []
    for exclusion in exclusions:
        if any(_exclusion_matches(v, exclusion) for v in violations):
            continue
        target = exclusion.get("function") or exclusion.get("lines", [])
        stale.append(
            {
                "file": exclusion.get("file", "<unknown>"),
                "line": 0,
                "rule": "stale-exclusion",
                "function": exclusion.get("function"),
                "message": (
                    f"Exclusion for {exclusion.get('file', '<unknown>')} "
                    f"({exclusion.get('rule', 'any rule')} @ {target}) matches no "
                    "finding. Either it has DRIFTED off its target (code moved "
                    "above it), in which case realign it — or the code was fixed, "
                    "in which case delete/remove the entry so it cannot silently "
                    "cover a future re-introduction."
                ),
            }
        )
    return stale


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


def run_audit(workspace: Path, json_mode: bool) -> int:
    """Audit ``workspace`` and return the process exit code.

    Split out of :func:`main` so the whole run — including the
    collected-nothing failure below — is reachable against an arbitrary
    workspace instead of only against this checkout.
    """
    if not json_mode:
        print("Auditing codebase for error hiding patterns...")
        print(f"Workspace: {workspace}\n")

    # A run that collected no files reports "no violations" and no stale
    # exclusions to match against — indistinguishable from a clean codebase,
    # and precisely how the absolute-path exclusion bug stayed quiet. There is
    # always something to audit in a real checkout, so zero candidates is a
    # broken invocation and is reported as a failure (Plan 00364 Task 5.4).
    candidates = collect_workspace_python_files(workspace) + collect_shell_files(workspace)
    if not candidates:
        print(
            f"error-hiding audit: no Python or shell files found under {workspace} "
            f"(searched {', '.join(AUDITED_DIRECTORIES)} plus "
            f"{', '.join(AUDITED_ROOT_FILES)}). Nothing was audited, so this run "
            "proves nothing — check the workspace path and the exclusion patterns.",
            file=sys.stderr,
        )
        return 1

    # Audit AUDITED_DIRECTORIES + AUDITED_ROOT_FILES (Plan 00200 Phase 5:
    # widened beyond "production code only" src/, which left the QA scripts
    # that IMPLEMENT the gates permanently exempt from the gate they enforce).
    all_violations = collect_python_violations(workspace) + collect_shell_violations(workspace)

    # Apply exclusions for intentional patterns (documented in
    # error_hiding_exclusions.json). They are read from the WORKSPACE being
    # audited, not from this file's own directory: an exclusion is a licence
    # for a specific finding in a specific tree, and reading another tree's
    # licences would report every one of them as stale.
    exclusions = load_exclusions(workspace / "scripts" / "qa")

    # Audit the exclusions themselves BEFORE applying them, against the
    # unfiltered set. A suppression file is otherwise only ever consulted to
    # REMOVE findings, so nothing asks whether each entry still earns its
    # place -- and a drifted entry exempts an innocent site while the real
    # finding resurfaces elsewhere looking like a brand-new violation.
    stale = find_stale_exclusions(all_violations, exclusions)

    all_violations = apply_exclusions(all_violations, exclusions) + stale

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


def main() -> int:
    """Main entry point: audit this checkout."""
    return run_audit(Path(__file__).parent.parent.parent, json_mode="--json" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
