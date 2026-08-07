#!/usr/bin/env python3
"""Audit shell scripts for stdout-capture corruption.

The v3.10.0 SEV-1 (Plan 00104) shipped because ``print_info`` accidentally
emitted to stdout instead of stderr. ``ensure_venv`` returns the resolved
venv path via ``echo "$venv_path"``, so callers capture it with
``VENV_PATH=$(ensure_venv ...)``. When ``print_info`` joined the same
stdout stream, ``$VENV_PATH`` ended up holding a multi-line blob with the
status message glued to the path, and every downstream check that compared
``$VENV_PATH`` to a real path quietly failed.

Unit tests caught nothing — the bug only manifests when stdout is captured.

This auditor performs two complementary static checks against shell scripts
in ``scripts/`` and ``src/.../skills/``:

  1. **Captured functions** — any function called via ``var=$(func ...)``
     somewhere in the repo is "return-via-stdout". Within its body, every
     ``echo``/``printf`` to stdout must be at a terminal-return position
     (immediately followed by ``return``/``return 0``, the function's
     closing ``}``, or a control-flow keyword that leads to one of those).

  2. **Log helpers** — functions whose name starts with ``print_``,
     ``log_``, ``warn_``, ``err_``, ``error_``, ``fail_``, ``die_``, or
     ``info_`` MUST redirect every ``echo``/``printf`` to ``>&2``. These
     are diagnostic helpers and have no business writing to stdout — the
     v3.10.0 SEV-1 was a missing ``>&2`` on ``print_info``.

Legitimate exceptions (rare) must carry an explicit marker:

    echo "non-return stdout"  # capture-audit: allow -- <reason>

The marker REQUIRES a ``-- <reason>`` suffix. A bare marker without reason
is itself a violation.

Usage:
    scripts/qa/audit_capture_corruption.py
    scripts/qa/audit_capture_corruption.py --json
    scripts/qa/audit_capture_corruption.py --scan-dir scripts/install
    scripts/qa/audit_capture_corruption.py --output /tmp/x.json

Exit codes:
    0 - clean
    1 - violations found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCAN_DIRS = (
    REPO_ROOT / "scripts",
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills",
)
DEFAULT_OUTPUT = REPO_ROOT / "untracked" / "qa" / "capture_corruption.json"

_FUNC_DEF_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\(\)\s*\{\s*$")
_FUNC_END_RE = re.compile(r"^}\s*$")

_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?")

_RETURN_RE = re.compile(r"^\s*return(\s+\S+)?\s*$")
_EXIT_RE = re.compile(r"^\s*exit(\s+\S+)?\s*$")

_MARKER_WITH_REASON = re.compile(r"#\s*capture-audit:\s*allow\s*--\s*\S")
_MARKER_WITHOUT_REASON = re.compile(r"#\s*capture-audit:\s*allow\b")

_ECHO_PRINTF_RE = re.compile(r"^\s*(?:echo|printf)\b")

_REDIRECT_STDERR_RE = re.compile(r">\s*&\s*2\b")
_REDIRECT_FILE_RE = re.compile(r"(?<!\d)(?<!&)>{1,2}\s*[^&\s]")
_PIPE_RE = re.compile(r"\|(?!\|)")

_CAPTURE_CALL_RE = re.compile(r"\$\(\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s|\)|$)")
_BACKTICK_CAPTURE_RE = re.compile(r"`\s*([a-zA-Z_][a-zA-Z0-9_]*)\b")

# Plan 00200 Task 1.6: a `cmd > file` / `cmd >> file` redirect is as risky as
# `$(cmd)` -- the run_lint.sh capture that started this plan was corrupted by
# exactly this shape (`venv_tool ruff ... > "${OUTPUT_FILE}.raw"`), which the
# original two rules had no regex to recognise at all. Scoped to a KNOWN
# function name as the line's first word so it never misfires on unrelated
# `>` usage elsewhere in the codebase -- e.g. `[[ "$a" > "$b" ]]` string
# comparison, whose first token is `[[`, never a function name.
_LEADING_KEYWORD_RE = re.compile(r"^\s*(?:if|elif|while|!)\s+")
_FIRST_WORD_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\b")

_LOG_HELPER_PREFIXES = (
    "print_",
    "log_",
    "warn_",
    "err_",
    "error_",
    "fail_",
    "die_",
    "info_",
)


@dataclass
class Violation:
    """A single capture-corruption finding."""

    file: str
    line: int
    function: str
    rule: str
    message: str


def _strip_inline_comment(line: str) -> str:
    """Strip the trailing ``#`` comment from a line, respecting quotes.

    Cheap heuristic — full shell tokenisation is unnecessary because the
    patterns we care about don't appear quoted in this codebase.
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
    return line


def _has_marker_with_reason(line: str) -> bool:
    return bool(_MARKER_WITH_REASON.search(line))


def _has_bare_marker(line: str) -> bool:
    return bool(_MARKER_WITHOUT_REASON.search(line)) and not _has_marker_with_reason(line)


def _line_writes_to_stdout(line: str) -> bool:
    """True iff this line's echo/printf goes to stdout (no redirect, no pipe)."""
    code = _strip_inline_comment(line)
    if not _ECHO_PRINTF_RE.search(code):
        return False
    if _REDIRECT_STDERR_RE.search(code):
        return False
    if _PIPE_RE.search(code):
        return False
    if _REDIRECT_FILE_RE.search(code):
        return False
    return True


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


@dataclass
class FunctionDef:
    """A single function definition extracted from a shell file."""

    name: str
    file: str
    start_line: int
    end_line: int
    body_lines: list[str]
    body_start: int
    function_level_marker: bool = False


def _strip_heredoc_bodies(lines: list[str]) -> list[str]:
    """Replace heredoc bodies with blank lines so echo/printf checks ignore them.

    Preserves line numbering. Heredoc opener and terminator stay intact;
    only the body lines are blanked.
    """
    out: list[str] = []
    expect_terminator: str | None = None
    for line in lines:
        if expect_terminator is not None:
            if line.strip() == expect_terminator:
                expect_terminator = None
                out.append(line)
            else:
                out.append("")
            continue
        match = _HEREDOC_OPEN_RE.search(line)
        if match:
            expect_terminator = match.group(1)
        out.append(line)
    return out


def _has_function_level_marker(lines: list[str], def_idx: int) -> bool:
    """True if the consecutive comment block above ``def_idx`` carries a marker.

    Walks backwards from the line above the function definition through
    contiguous ``#`` comment lines (stopping at the first blank / code line).
    A bare marker without reason is not honoured here — it surfaces as a
    line-level violation in the body if any stdout write triggers the rule.
    """
    j = def_idx - 1
    while j >= 0:
        stripped = lines[j].strip()
        if stripped == "" or not stripped.startswith("#"):
            return False
        if _has_marker_with_reason(lines[j]):
            return True
        j -= 1
    return False


def _extract_functions(lines: list[str], filepath: str) -> list[FunctionDef]:
    """Walk the file and extract top-level function bodies.

    We only recognise the canonical ``name() {`` opener with closing ``}``
    at column 0 — the convention used throughout ``scripts/``. Nested and
    one-line ``func() { cmd; }`` definitions are not supported.
    """
    funcs: list[FunctionDef] = []
    i = 0
    while i < len(lines):
        m = _FUNC_DEF_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        marker = _has_function_level_marker(lines, i)
        body_start = i + 1
        j = body_start
        found_end = False
        while j < len(lines):
            if _FUNC_END_RE.match(lines[j]):
                funcs.append(
                    FunctionDef(
                        name=name,
                        file=filepath,
                        start_line=i + 1,
                        end_line=j + 1,
                        body_lines=lines[body_start:j],
                        body_start=body_start,
                        function_level_marker=marker,
                    )
                )
                i = j + 1
                found_end = True
                break
            j += 1
        if not found_end:
            i = j
    return funcs


def _collect_captured_function_names(lines: list[str]) -> set[str]:
    """Find every function name appearing in a ``$(name ...)`` capture."""
    names: set[str] = set()
    for line in lines:
        for match in _CAPTURE_CALL_RE.finditer(line):
            names.add(match.group(1))
        for match in _BACKTICK_CAPTURE_RE.finditer(line):
            names.add(match.group(1))
    return names


def _collect_redirect_consumed_names(lines: list[str], known_functions: set[str]) -> set[str]:
    """Known function names invoked on a line that redirects stdout to a file.

    ``>``/``>>`` only -- never ``>&2``, via the same ``_REDIRECT_FILE_RE``
    used to decide whether an individual echo/printf line writes to stdout.
    """
    names: set[str] = set()
    for line in lines:
        code = _strip_inline_comment(line)
        if not _REDIRECT_FILE_RE.search(code):
            continue
        stripped = _LEADING_KEYWORD_RE.sub("", code, count=1)
        match = _FIRST_WORD_RE.match(stripped)
        if match and match.group(1) in known_functions:
            names.add(match.group(1))
    return names


def _collect_bare_calls(body_lines: list[str], known_functions: set[str]) -> set[str]:
    """Known function names invoked as the first word of a line in a body.

    Deliberately excludes ``$(...)``/backtick captures: their first token is
    the assignment's LHS variable (if any), never the called function name,
    so those are naturally not matched here -- they're already independently
    classified by ``_collect_captured_function_names``. Also does not follow
    a call appearing after an ``&&``/``||`` chain on the same line (a known,
    documented scope limit; see Plan 00200 Task 1.6 journal entry).
    """
    names: set[str] = set()
    for line in body_lines:
        code = _strip_inline_comment(line)
        stripped = _LEADING_KEYWORD_RE.sub("", code, count=1)
        match = _FIRST_WORD_RE.match(stripped)
        if match and match.group(1) in known_functions:
            names.add(match.group(1))
    return names


def _resolve_definitions(names: set[str], func_defs: list[FunctionDef]) -> set[tuple[str, str]]:
    """Resolve bare names to specific ``(file, name)`` definitions.

    A name defined in exactly one file resolves unambiguously. A name
    defined in MORE THAN ONE file (this codebase has one such collision:
    two unrelated ``ensure_venv`` functions, in ``venv-include.bash`` and
    ``scripts/install/venv.sh``) is deliberately left unresolved here rather
    than guessed at -- a purely regex-based auditor cannot know which
    definition a given call site's shell would actually resolve to without
    tracking source order, and guessing wrong manufactures a false positive
    against a same-named function that was never actually at risk (Plan
    00200 Task 1.6 journal entry). Ambiguous names reachable ONLY by
    propagation are still resolved correctly by ``_propagate_redirect_consumption``,
    which has caller-file context this function does not.
    """
    by_name: dict[str, list[FunctionDef]] = {}
    for f in func_defs:
        by_name.setdefault(f.name, []).append(f)

    resolved: set[tuple[str, str]] = set()
    for name in names:
        candidates = by_name.get(name, [])
        if len(candidates) == 1:
            resolved.add((candidates[0].file, name))
    return resolved


def _propagate_redirect_consumption(
    redirect_consumed: set[tuple[str, str]],
    func_defs: list[FunctionDef],
) -> set[tuple[str, str]]:
    """Fixed-point closure over the caller graph of redirect-consumed functions.

    A function invoked (bare, not ``$(...)``) from within the body of an
    already redirect-consumed function inherits the same zero-tolerance
    stdout requirement: its output shares the same redirected stream as its
    caller's. This is what's needed to catch the actual historical shape --
    ``venv_tool`` is redirected, and it calls ``ensure_venv`` (whose stray
    echo was the real bug) by bare name, not ``$(...)``.

    Resolves each callee PREFERRING a definition in the SAME FILE as the
    caller (the only scoping signal a cross-file, name-based regex auditor
    can safely use) before falling back to a global unambiguous match; a
    name that is ambiguous AND has no same-file candidate is left
    unresolved rather than guessed at, for the same reason
    ``_resolve_definitions`` does -- this is exactly what keeps the
    ``ensure_venv`` name collision from flagging the unrelated,
    never-redirected ``scripts/install/venv.sh`` definition.
    """
    by_file_name: dict[tuple[str, str], FunctionDef] = {(f.file, f.name): f for f in func_defs}
    by_name: dict[str, list[FunctionDef]] = {}
    for f in func_defs:
        by_name.setdefault(f.name, []).append(f)
    known_functions = set(by_name)

    consumed = set(redirect_consumed)
    changed = True
    while changed:
        changed = False
        for file, name in list(consumed):
            func = by_file_name.get((file, name))
            if func is None:
                continue
            for called in _collect_bare_calls(func.body_lines, known_functions):
                if (file, called) in by_file_name:
                    target = (file, called)
                else:
                    candidates = by_name.get(called, [])
                    if len(candidates) != 1:
                        continue  # ambiguous, no same-file candidate -- skip
                    target = (candidates[0].file, called)
                if target not in consumed:
                    consumed.add(target)
                    changed = True
    return consumed


def _is_log_helper_name(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in _LOG_HELPER_PREFIXES)


_IF_OPEN_RE = re.compile(r"^\s*(if|case)\b")
_FI_CLOSE_RE = re.compile(r"^\s*(fi|esac)\s*(?:#.*)?$")
_ALT_BRANCH_RE = re.compile(r"^\s*(else|elif\b.*|;;)\s*(?:#.*)?$")
_INERT_KEYWORD_RE = re.compile(r"^\s*(then|do|done)\s*(?:#.*)?$")


def _is_terminal_return_position(body: list[str], idx: int) -> bool:
    """True iff every code path forward from ``body[idx]`` exits the function.

    Tracks if/case nesting depth RELATIVE to ``idx``. ``depth >= 0`` means we
    are at idx's nesting or deeper; ``depth < 0`` means we have left the
    if/case that idx was inside and are back at a shallower level (or the
    function top). For each depth we track ``in_alt_at[d]`` — whether we
    have crossed ``else``/``elif``/``;;`` at that depth, putting us into a
    sibling branch of idx's branch.

    A subsequent stdout emit is "shadowed" (does not affect idx) iff any
    depth ``0..current_depth`` is in an alt branch. Once we go below depth
    0 (exit idx's enclosing block), no shadow applies — anything we hit
    runs sequentially after idx and breaks the terminal-return guarantee.

    Terminal if we reach ``return``/``exit`` from a non-shadowed position,
    or fall off the end of the body. Non-terminal if we hit any other
    command (echo or otherwise) from a non-shadowed position.
    """
    depth = 0
    in_alt_at: dict[int, bool] = {}

    def in_shadow(d: int) -> bool:
        if d < 0:
            return False
        return any(in_alt_at.get(level, False) for level in range(d + 1))

    for j in range(idx + 1, len(body)):
        line = body[j]
        if _is_blank_or_comment(line):
            continue
        if _INERT_KEYWORD_RE.match(line):
            continue
        if _RETURN_RE.match(line):
            if not in_shadow(depth):
                return True
            continue
        if _EXIT_RE.match(line):
            if not in_shadow(depth):
                return True
            continue
        if _IF_OPEN_RE.match(line):
            depth += 1
            in_alt_at[depth] = False
            continue
        if _FI_CLOSE_RE.match(line):
            in_alt_at.pop(depth, None)
            depth -= 1
            continue
        if _ALT_BRANCH_RE.match(line):
            if depth >= 0:
                in_alt_at[depth] = True
            continue
        if _line_writes_to_stdout(line):
            if in_shadow(depth):
                continue
            return False
        if in_shadow(depth):
            continue
        return False
    return True


def _audit_function_body(
    func: FunctionDef,
    *,
    enforce_terminal: bool,
    enforce_all_stderr: bool,
    is_log_helper: bool,
) -> list[Violation]:
    """Walk a function body and emit violations.

    - ``enforce_terminal``: function is ``$(...)``-captured. Stdout writes
      are OK only at terminal-return positions -- the privileged "this is
      the function's intended return value" position.
    - ``enforce_all_stderr``: no privileged position exists. Stdout writes
      are never OK regardless of position -- true for log helpers (their
      whole purpose is diagnostics, never a return value) AND for functions
      whose stdout is consumed via ``>``/``>>`` redirect (a redirect
      concatenates the ENTIRE stream, including whatever runs after this
      function returns, so there is no "last echo is the payload" escape
      the way there is for a single ``$(...)`` capture -- Plan 00200 Task
      1.6). ``is_log_helper`` only selects which of those two the message
      names; the enforcement is identical either way.
    """
    violations: list[Violation] = []
    body = func.body_lines

    for idx, line in enumerate(body):
        if not _line_writes_to_stdout(line):
            continue

        if _has_marker_with_reason(line):
            continue
        if idx > 0 and _has_marker_with_reason(body[idx - 1]):
            continue

        absolute_lineno = func.body_start + idx + 1

        if _has_bare_marker(line):
            violations.append(
                Violation(
                    file=func.file,
                    line=absolute_lineno,
                    function=func.name,
                    rule="marker-missing-reason",
                    message=(
                        "capture-audit marker present but no reason given; "
                        "add '-- <why this stdout write is correct>'"
                    ),
                )
            )
            continue

        if enforce_all_stderr:
            if is_log_helper:
                rule = "log-helper-stdout"
                message = (
                    f"log helper '{func.name}' writes to stdout; redirect "
                    "with '>&2' so it doesn't corrupt VAR=$(captured-func) "
                    "callers (v3.10.0 SEV-1 root cause)"
                )
            else:
                rule = "capture-corruption"
                message = (
                    f"function '{func.name}' is invoked with its stdout "
                    "redirected to a file elsewhere (directly, or via a "
                    "caller that is) -- ANY stdout write here, not just a "
                    "non-terminal one, lands in that file. Redirect with "
                    "'>&2', or add '# capture-audit: allow -- <reason>'"
                )
            violations.append(
                Violation(
                    file=func.file,
                    line=absolute_lineno,
                    function=func.name,
                    rule=rule,
                    message=message,
                )
            )
            continue

        if enforce_terminal and not _is_terminal_return_position(body, idx):
            violations.append(
                Violation(
                    file=func.file,
                    line=absolute_lineno,
                    function=func.name,
                    rule="capture-corruption",
                    message=(
                        f"function '{func.name}' is captured via $(...) elsewhere; "
                        "this echo/printf is not at a terminal return position and "
                        "would corrupt the captured value. Redirect with '>&2', or "
                        "add '# capture-audit: allow -- <reason>'"
                    ),
                )
            )

    return violations


def _audit_with_known_functions(
    func_defs: list[FunctionDef],
    captured_names: set[str],
    redirect_consumed_defs: set[tuple[str, str]],
) -> list[Violation]:
    violations: list[Violation] = []
    for func in func_defs:
        is_captured = func.name in captured_names
        is_redirect_consumed = (func.file, func.name) in redirect_consumed_defs
        is_log_helper = _is_log_helper_name(func.name)

        # Plan 00200 Task 1.6 journal entry: the function-level marker is
        # deliberately scoped to `is_captured` ONLY, never `is_redirect_consumed`.
        # It exists to rebut a specific, stated reason (typically the name
        # collision this same-named function has with an unrelated $(...)
        # -captured definition elsewhere) -- it says nothing about redirect
        # risk, which is a different, independently-derived signal (real
        # call-graph analysis, not a name collision). Blanket-clearing both
        # from one marker is exactly the "guard exists but doesn't cover it"
        # shape this rule was added to close: it is what let the historical
        # ensure_venv bug ship even in a repo that already HAD a marker
        # convention. A genuine redirect-consumption false positive still has
        # an escape hatch -- the per-line ``# capture-audit: allow -- <reason>``
        # marker works uniformly across all three rules.
        if func.function_level_marker:
            is_captured = False

        if not (is_captured or is_redirect_consumed or is_log_helper):
            continue

        # Redirect consumption and log-helper status both mean "zero
        # tolerance, no privileged terminal position" (Plan 00200 Task 1.6);
        # a bare $(...) capture alone keeps the lenient terminal-position
        # check. When both apply, zero tolerance wins -- it is the stricter
        # requirement.
        zero_tolerance = is_redirect_consumed or is_log_helper

        violations.extend(
            _audit_function_body(
                func,
                enforce_terminal=is_captured,
                enforce_all_stderr=zero_tolerance,
                is_log_helper=is_log_helper,
            )
        )
    return violations


def audit_files(paths: list[Path]) -> list[Violation]:
    """Audit a list of shell file paths together (cross-file capture detection).

    Two passes over the files: the first extracts every function definition
    (needed to build the known-function-name universe redirect-consumption
    detection scopes against, Plan 00200 Task 1.6); the second collects the
    ``$(...)``-captured and redirect-consumed name sets now that the known
    set exists, then closes the redirect-consumed set over the caller graph.
    """
    per_file_lines: list[list[str]] = []
    all_func_defs: list[FunctionDef] = []

    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"could not read {path}: {exc}") from exc
        raw_lines = source.splitlines()
        lines = _strip_heredoc_bodies(raw_lines)
        per_file_lines.append(lines)
        all_func_defs.extend(_extract_functions(lines, str(path)))

    known_functions = {f.name for f in all_func_defs}

    all_captured: set[str] = set()
    redirect_consumed_names: set[str] = set()
    for lines in per_file_lines:
        all_captured.update(_collect_captured_function_names(lines))
        redirect_consumed_names.update(_collect_redirect_consumed_names(lines, known_functions))

    redirect_consumed_defs = _resolve_definitions(redirect_consumed_names, all_func_defs)
    redirect_consumed_defs = _propagate_redirect_consumption(redirect_consumed_defs, all_func_defs)

    return _audit_with_known_functions(all_func_defs, all_captured, redirect_consumed_defs)


_EXCLUDE_DIR_PARTS = {
    "untracked",
    "__pycache__",
    ".git",
    "node_modules",
}


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDE_DIR_PARTS for part in path.parts)


def _collect_shell_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*.sh", "*.bash"):
            for script in sorted(root.rglob(pattern)):
                if _is_excluded(script):
                    continue
                resolved = script.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                files.append(script)
    return files


def _format_text_report(violations: list[Violation]) -> str:
    if not violations:
        return "capture-audit: no violations\n"
    lines = [f"capture-audit: {len(violations)} violation(s)\n"]
    for v in violations:
        lines.append(f"  {v.file}:{v.line}  [{v.function}]  [{v.rule}]  {v.message}")
    return "\n".join(lines) + "\n"


def _write_json(violations: list[Violation], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tool": "capture-corruption",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": [asdict(v) for v in violations],
    }
    output_path.write_text(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output to --output (default: untracked/qa/capture_corruption.json)",
    )
    parser.add_argument(
        "--scan-dir",
        type=Path,
        action="append",
        default=None,
        help="Directory to scan; may be repeated (default: scripts/ + src/.../skills/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write JSON (only when --json is given)",
    )
    args = parser.parse_args(argv)

    scan_dirs = args.scan_dir if args.scan_dir else list(DEFAULT_SCAN_DIRS)
    files = _collect_shell_files(scan_dirs)

    if not files:
        print(
            "capture-audit: no shell files found in scan directories: "
            + ", ".join(str(d) for d in scan_dirs),
            file=sys.stderr,
        )
        return 1

    violations = audit_files(files)

    if args.json:
        _write_json(violations, args.output)
    else:
        sys.stdout.write(_format_text_report(violations))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
