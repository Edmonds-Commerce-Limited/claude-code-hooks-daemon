#!/usr/bin/env python3
"""Check that every inline QA suppression carries its reasoning.

Owner ruling B2 (Plan 00483, applied by Plan 00484 gap G1): suppressions stay
inline, co-located with the code they excuse, and each MUST carry its
reasoning. There is no central exceptions file and no baseline, so the only
thing that can keep a reasonless suppression out of the tree is a detector
that fails on one. This is that detector.

A suppression is honoured when its reason is in any of three places:

- the same comment, after the directive and its codes
  (``nosec B404 - only the type is named``);
- another ``#`` segment of the same comment
  (``noqa: E501  # the URL cannot be wrapped``);
- the block of own-line comments directly above, with no blank line or code
  between (a ``# SECURITY:`` paragraph above an import).

The generic-reason check is the one the ``MUST_*_BECAUSE`` hatches use
(``utils.escape_hatch.is_acceptable_reason``): it cannot judge whether a reason
is TRUE, only that it says something.

Directives judged: ``nosec``, ``noqa``, ``type: ignore``, ``nosemgrep``,
``pragma: no cover`` and ``shellcheck disable``. A formatter marker
(``fmt: skip``) is not a QA suppression and is not judged.

**Comments, not text.** Python is read with ``tokenize``, so a directive named
inside a string or docstring (the ``qa_suppression`` handler's fixtures, prose
about the directives) is never a finding. Shell is read as own-line comments,
which is the only place ``shellcheck`` honours a directive. A directive counts
only at the START of a comment segment, so prose that merely mentions one does
not.

Usage:
    python scripts/qa/check_inline_suppressions.py [--json] [--path DIR]

Exit codes:
    0 - Every suppression carries a reason
    1 - A suppression has none, a file could not be read, or nothing was scanned
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Any, Final, NamedTuple

from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
    PythonQaSuppressionStrategy,
)
from claude_code_hooks_daemon.utils.escape_hatch import is_acceptable_reason
from claude_code_hooks_daemon.utils.path_containment import path_relative_to
from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _PROJECT_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "inline_suppressions.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

RULE_NO_REASON: Final[str] = "inline-suppression-without-reason"
RULE_UNREADABLE: Final[str] = "unreadable-file"

#: Gitignored runtime state, never project source. Matched on the path BELOW the
#: scan root (00466 N26), never on the absolute path.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "untracked",
        "venv",
        ".venv",
        "worktrees",
    }
)

_PYTHON_SUFFIX: Final[str] = ".py"
_SHELL_SUFFIXES: Final[frozenset[str]] = frozenset({".sh", ".bash"})
_SHEBANG: Final[str] = "#!"
_SHELL_INTERPRETERS: Final[tuple[str, ...]] = ("sh", "bash", "dash", "zsh")
_MAX_BYTES: Final[int] = 2_000_000

#: Where each directive's own codes end. What follows is the free text.
#: Each pattern is anchored at the START of a comment segment.
#: A Bandit code (``B603``) or test name (``subprocess_without_shell_equals_true``)
#: names the check that is silenced, never why, so both belong to the directive.
_BANDIT_CODE: Final[str] = r"(?:B\d{3}|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)"
_DIRECTIVES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("nosec", re.compile(rf"nosec\b(?:\s*:)?(?:[\s,]*{_BANDIT_CODE})*", re.IGNORECASE)),
    (
        "noqa",
        re.compile(
            r"(?:(?:ruff|flake8)\s*:\s*)?noqa\b" r"(?:\s*:\s*[A-Za-z]+\d+(?:[\s,]+[A-Za-z]+\d+)*)?",
            re.IGNORECASE,
        ),
    ),
    ("type: ignore", re.compile(r"type:\s*ignore\b(?:\[[^\]]*\])?", re.IGNORECASE)),
    ("nosemgrep", re.compile(r"nosemgrep\b(?:\s*:\s*[\w./-]+)?", re.IGNORECASE)),
    ("pragma: no cover", re.compile(r"pragma:\s*no\s+cover\b", re.IGNORECASE)),
    (
        "shellcheck disable",
        re.compile(r"shellcheck\s+disable\s*=\s*[A-Za-z0-9,]+", re.IGNORECASE),
    ),
    (
        "pyright config",
        re.compile(r"pyright:\s*report\w+\s*=\s*\w+(?:\s*,\s*report\w+\s*=\s*\w+)*", re.IGNORECASE),
    ),
)

#: The directives the ``qa_suppression`` write-time handler already forbids, read from
#: its Python strategy so the two lists cannot drift. Each starts ``#\s*``.
PROJECT_FORBIDDEN_PATTERNS: Final[tuple[str, ...]] = (
    PythonQaSuppressionStrategy().forbidden_patterns
)
_PROJECT_DIRECTIVES: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in PROJECT_FORBIDDEN_PATTERNS
)
#: What may follow a project directive before its free text: ``[codes]`` or ``=codes``.
_PROJECT_CODES: Final[re.Pattern[str]] = re.compile(r"(?:\[[^\]]*\]|=[\w,.-]+)?")

#: A cheap test over a whole file, so only files that could hold a directive are tokenised.
_PREFILTER: Final[re.Pattern[str]] = re.compile(
    "|".join(
        (
            r"nosec|noqa|nosemgrep|type:\s*ignore|pragma:\s*no\s+cover|shellcheck\s+disable",
            r"pyright:\s*report",
            *PROJECT_FORBIDDEN_PATTERNS,
        )
    ),
    re.IGNORECASE,
)

#: Words that make a comment block above a directive ABOUT the suppression. A block
#: that names neither the directive's own words and codes nor one of these is about
#: something else, and an unrelated neighbour is not a reason.
_RELEVANT_WORDS: Final[tuple[str, ...]] = (
    "suppress",
    "silence",
    "false positive",
    "false-positive",
    "unreachable",
    "security",
    "deliberate",
    "intentional",
    "on purpose",
)

_EN_DASH: Final[str] = chr(0x2013)
_EM_DASH: Final[str] = chr(0x2014)
_LEADING_FILLER: Final[str] = f" \t:-{_EN_DASH}{_EM_DASH},;"


class ParsedComment(NamedTuple):
    """A comment's directives, the free text that could be their reason, and their own words."""

    directives: list[str]
    reason_text: str
    subjects: frozenset[str]


def _match_directive(segment: str) -> tuple[str, int] | None:
    """``(name, end)`` of the directive STARTING ``segment``, ``end`` past its codes."""
    text = segment.lstrip(_LEADING_FILLER)
    for name, pattern in _DIRECTIVES:
        match = pattern.match(text)
        if match:
            return name, len(segment) - len(text) + match.end()
    hashed = "#" + segment
    for pattern in _PROJECT_DIRECTIVES:
        match = pattern.match(hashed)
        if match:
            codes = _PROJECT_CODES.match(hashed, match.end())
            end = codes.end() if codes else match.end()
            return " ".join(hashed[1 : match.end()].split()), end - 1
    return None


def parse_comment(comment: str) -> ParsedComment:
    """The directives in ``comment`` (its text after the first ``#``) and its free text.

    The comment is split on ``#`` into segments. A segment that STARTS with a
    directive is one; whatever follows the directive's codes, and every other
    segment, is free text.
    """
    directives: list[str] = []
    free: list[str] = []
    subjects: set[str] = set()
    for segment in comment.split("#"):
        found = _match_directive(segment)
        if found is None:
            free.append(segment.lstrip(_LEADING_FILLER))
            continue
        name, end = found
        directives.append(name)
        subjects.update(word.lower() for word in re.findall(r"[\w.-]+", segment[:end]))
        free.append(segment[end:].lstrip(_LEADING_FILLER))
    return ParsedComment(
        directives, " ".join(part for part in free if part.strip()), frozenset(subjects)
    )


def _is_about(block: str, subjects: frozenset[str]) -> bool:
    """Whether ``block`` names the suppression's own words or codes, or says it is one."""
    lowered = block.lower()
    words = set(re.findall(r"[\w.-]+", lowered))
    return bool(words & subjects) or any(word in lowered for word in _RELEVANT_WORDS)


class CommentLine(NamedTuple):
    """One comment, and whether it is alone on its line."""

    text: str
    own_line: bool


def _python_comments(source: str) -> dict[int, CommentLine]:
    """Every comment in ``source`` by 1-indexed line; strings are never comments.

    Raises:
        tokenize.TokenError: the source ends inside a bracket or string.
        SyntaxError: the source cannot be tokenised (an ``IndentationError`` too).
    """
    found: dict[int, CommentLine] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            found[token.start[0]] = CommentLine(
                token.string[1:], token.line.lstrip().startswith("#")
            )
    return found


def _shell_comments(source: str) -> dict[int, CommentLine]:
    """Own-line comments in shell ``source`` by 1-indexed line (the shebang is not one)."""
    found: dict[int, CommentLine] = {}
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#") and not stripped.startswith(_SHEBANG):
            found[number] = CommentLine(stripped[1:], True)
    return found


def _block_above(comments: dict[int, CommentLine], line: int) -> str:
    """The reason text of the own-line comment block touching ``line`` from above.

    A comment that is itself a directive contributes no text, but does not end
    the block, so one paragraph can sit above several consecutive directives.
    """
    parts: list[str] = []
    number = line - 1
    while number in comments and comments[number].own_line:
        parsed = parse_comment(comments[number].text)
        parts.append(parsed.reason_text if parsed.directives else comments[number].text.strip())
        number -= 1
    return " ".join(reversed(parts))


def judge_comments(comments: dict[int, CommentLine]) -> tuple[int, list[tuple[int, str]]]:
    """How many suppressions ``comments`` hold, and the ``(line, directive)`` of each reasonless one."""
    total = 0
    reasonless: list[tuple[int, str]] = []
    for line in sorted(comments):
        parsed = parse_comment(comments[line].text)
        total += len(parsed.directives)
        if not parsed.directives:
            continue
        if is_acceptable_reason(parsed.reason_text):
            continue
        above = _block_above(comments, line)
        if is_acceptable_reason(above) and _is_about(above, parsed.subjects):
            continue
        reasonless.extend((line, name) for name in parsed.directives)
    return total, reasonless


def _is_shell(path: Path, head: str) -> bool:
    """Whether ``path`` is a shell script: by suffix, or an extensionless shebang."""
    if path.suffix in _SHELL_SUFFIXES:
        return True
    if path.suffix or not head.startswith(_SHEBANG):
        return False
    words = head[len(_SHEBANG) :].split()
    names = [Path(word).name for word in words[:2]]
    return any(name in _SHELL_INTERPRETERS for name in names)


def _candidate_files(root: Path) -> tuple[list[Path], int]:
    """The files that could hold a directive, and how many files the walk saw."""
    walked = walk_files(root)
    found = [
        path
        for path in walked
        if not any(part in _SKIP_DIRS for part in relative_parts(path, root))
        and path.is_file()
        and not path.is_symlink()
        and (path.suffix == _PYTHON_SUFFIX or path.suffix in _SHELL_SUFFIXES or not path.suffix)
    ]
    return found, len(walked)


class ScanResult(NamedTuple):
    """What a scan of one tree found."""

    violations: list[dict[str, Any]]
    files_scanned: int
    files_seen: int
    suppressions_found: int


def _violation(relative: str, line: int, rule: str, directive: str, message: str) -> dict[str, Any]:
    return {
        "file": relative,
        "line": line,
        "rule": rule,
        "directive": directive,
        "message": message,
    }


def _scan_file(path: Path, relative: str) -> tuple[bool, int, list[dict[str, Any]]]:
    """``(examined, suppressions, violations)`` for one file; ``examined`` is False when skipped."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            return False, 0, []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return True, 0, [_violation(relative, 0, RULE_UNREADABLE, "", f"could not be read: {exc}")]
    head = text.split("\n", 1)[0]
    shell = _is_shell(path, head)
    if path.suffix != _PYTHON_SUFFIX and not shell:
        return False, 0, []
    if not _PREFILTER.search(text):
        return True, 0, []
    try:
        comments = _shell_comments(text) if shell else _python_comments(text)
    except (tokenize.TokenError, SyntaxError) as exc:
        return (
            True,
            0,
            [_violation(relative, 0, RULE_UNREADABLE, "", f"could not be tokenised: {exc}")],
        )
    total, reasonless = judge_comments(comments)
    found = [
        _violation(
            relative,
            line,
            RULE_NO_REASON,
            name,
            f"`{name}` has no reason: say why, after the directive, in the same comment, "
            "or in the comment block directly above",
        )
        for line, name in reasonless
    ]
    return True, total, found


def scan(root: Path) -> ScanResult:
    """Judge every suppression below ``root``."""
    candidates, seen = _candidate_files(root)
    violations: list[dict[str, Any]] = []
    scanned = 0
    suppressions = 0
    for path in candidates:
        relative = path_relative_to(path, root).as_posix()
        examined, count, found = _scan_file(path, relative)
        scanned += examined
        suppressions += count
        violations.extend(found)
    return ScanResult(violations, scanned, seen, suppressions)


def find_violations(root: Path) -> list[dict[str, Any]]:
    """Every reasonless suppression and unreadable file below ``root``."""
    return scan(root).violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_PROJECT_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    result = scan(root)
    vacuous = vacuous_scan_failure(
        examined=result.files_scanned, candidates=result.files_seen, noun="files", root=root
    )
    violations = result.violations

    if args.json_output:
        # A --path scan answers "is this DIRECTORY clean", which is not the
        # question the repository artefact answers; it reports beside what it scanned.
        output_file = root / _ARTEFACT_NAME if root != _PROJECT_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(
                {
                    "summary": {
                        "passed": not violations and vacuous is None,
                        "vacuous_scan": vacuous,
                        "total_violations": len(violations),
                        "files_scanned": result.files_scanned,
                        "suppressions_found": result.suppressions_found,
                    },
                    "violations": violations,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        for item in violations:
            print(f"{item['file']}:{item['line']}  {item['message']}")
        print(
            f"\n{len(violations)} violation(s) ({result.suppressions_found} suppressions "
            f"in {result.files_scanned} files scanned)"
        )
    if vacuous is not None:
        print(f"FAILED: {vacuous}", file=sys.stderr)

    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
