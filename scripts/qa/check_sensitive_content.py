#!/usr/bin/env python3
"""Whole-tree QA backstop for the ``sensitive_content`` handler (Plan 00201).

The ``sensitive_content`` PreToolUse handler only sees content arriving
through Claude Code's own ``Write``/``Edit`` tools. Content can also arrive
in the tracked tree other ways — ``git mv``, an external editor, another
agent, a manual commit — none of which the daemon ever observes. This script
is the backstop: it scans the whole GIT-TRACKED tree (``git ls-files``, never
a filesystem walk, so it only ever reports what would actually ship) against
the SAME two sources the handler enforces:

- **Public patterns** (``handlers.pre_tool_use.sensitive_content.options.
  public_patterns`` in ``.claude/hooks-daemon.yaml``) — reported with the
  pattern name and the matched text, exactly like the handler's own deny
  reason. Safe to name.
- **Secret word list** (``.claude/block-words.secret`` by default, itself
  gitignored so ``git ls-files`` never lists it as a scan TARGET) — reported
  with ``file:line`` and a rule INDEX only, never the term. This mirrors
  ``utils/secret_redaction.py`` exactly (imported, not reimplemented) so the
  two enforcement surfaces can never disagree about what counts as a secret.

Usage:
    python scripts/qa/check_sensitive_content.py [--json] [--path DIR] [--config FILE]

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "sensitive_content.json"
_DEFAULT_CONFIG: Final[Path] = _REPO_ROOT / ".claude" / "hooks-daemon.yaml"

_PUBLIC_RULE_PREFIX: Final[str] = "public-pattern"
_SECRET_RULE: Final[str] = "secret-word-list"
# A filename violation belongs to no line of the file; 0 is never a real
# 1-based line number, so it reads unambiguously as "the name, not the body".
_FILENAME_LINE: Final[int] = 0

_PATTERN_KEY_NAME: Final[str] = "name"
_PATTERN_KEY_PATTERN: Final[str] = "pattern"
_PATTERN_KEY_DESCRIPTION: Final[str] = "description"


@dataclass(frozen=True)
class Violation:
    """A single flagged occurrence.

    ``message`` is the ONLY field a secret-list match may populate with
    anything beyond an index/count — every caller must keep it that way.
    """

    file: str
    line: int
    rule: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "rule": self.rule, "message": self.message}


def _tracked_files(repo_root: Path) -> list[Path]:
    """Every git-tracked file, as absolute paths.

    Uses ``git ls-files`` (not a filesystem walk) so the scan matches exactly
    what a fresh clone receives — a gitignored file (including the secret
    word list itself) is structurally never a scan TARGET.
    """
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [repo_root / name for name in result.stdout.split("\0") if name]


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _sensitive_content_options(config: dict[str, Any]) -> dict[str, Any]:
    handlers = config.get("handlers", {})
    pre_tool_use = handlers.get("pre_tool_use", {}) if isinstance(handlers, dict) else {}
    handler_cfg = (
        pre_tool_use.get("sensitive_content", {}) if isinstance(pre_tool_use, dict) else {}
    )
    options = handler_cfg.get("options", {}) if isinstance(handler_cfg, dict) else {}
    return options if isinstance(options, dict) else {}


def load_public_patterns(config_path: Path) -> list[dict[str, str]]:
    """Public patterns from the SAME config key the handler reads."""
    options = _sensitive_content_options(_load_config(config_path))
    patterns = options.get("public_patterns", [])
    return patterns if isinstance(patterns, list) else []


def load_exclude_paths(config_path: Path) -> list[str]:
    """Exclude-path globs from the SAME config key the handler reads.

    Kept additive-only here (unlike the handler, this script has no
    project-wide ``daemon.exclude_paths`` context) — a whole-tree scan is
    deliberately stricter than the live handler.
    """
    options = _sensitive_content_options(_load_config(config_path))
    patterns = options.get("exclude_paths", [])
    return [p for p in patterns if isinstance(p, str)] if isinstance(patterns, list) else []


def resolve_secret_word_list_file(config_path: Path, repo_root: Path) -> Path | None:
    """Resolved secret-word-list path via ``utils/secret_redaction`` — the SSoT.

    ``None`` when the daemon package is not importable in whatever
    interpreter ran this script (e.g. system Python rather than the venv) —
    matching ``audit_error_hiding.py``'s own precedent of importing the
    daemon package from a QA script.
    """
    try:
        from claude_code_hooks_daemon.utils.secret_redaction import (
            resolve_secret_word_list_path,
        )
    except ImportError:
        return None

    options = _sensitive_content_options(_load_config(config_path))
    configured = options.get("secret_word_list_path")
    return resolve_secret_word_list_path(
        configured if isinstance(configured, str) else None, repo_root
    )


def resolve_secret_terms(config_path: Path, repo_root: Path) -> tuple[str, ...]:
    """Secret-list terms via ``utils/secret_redaction`` — the single source of truth."""
    path = resolve_secret_word_list_file(config_path, repo_root)
    if path is None:
        return ()
    from claude_code_hooks_daemon.utils.secret_redaction import load_secret_terms

    return load_secret_terms(path)


def filter_excluded_files(
    files: list[Path], exclude_globs: list[str], project_root: Path
) -> list[Path]:
    """Drop any file matching an ``exclude_paths`` glob, via ``utils/path_exclusion`` — the SSoT.

    A no-op (returns ``files`` unchanged) when there are no globs, or when the
    daemon package is not importable in whatever interpreter ran this script —
    matching this module's other lazy-import-with-graceful-degrade precedent.
    """
    if not exclude_globs:
        return files
    try:
        from claude_code_hooks_daemon.utils.path_exclusion import is_path_excluded
    except ImportError:
        return files

    return [
        f for f in files if not is_path_excluded(str(f), exclude_globs, project_root=project_root)
    ]


def _compile_public_patterns(
    patterns: list[dict[str, str]],
) -> list[tuple[dict[str, str], re.Pattern[str]]]:
    compiled: list[tuple[dict[str, str], re.Pattern[str]]] = []
    for entry in patterns:
        pattern = entry.get(_PATTERN_KEY_PATTERN, "")
        if not pattern:
            continue
        try:
            compiled.append((entry, re.compile(pattern, re.IGNORECASE)))
        except re.error:
            continue
    return compiled


def _never_matches(_text: str, _term: str) -> bool:
    """Stand-in matcher used when the daemon package is not importable.

    ``resolve_secret_terms`` already returns an empty tuple in that case, so
    this is never consulted with a real term — it exists so the matcher is
    always a callable and callers need no None-handling.
    """
    return False


def resolve_term_matcher() -> Callable[[str, str], bool]:
    """The shared secret-term predicate from ``utils/secret_redaction``.

    Resolved ONCE and injected, rather than reimplemented here. The scanner
    previously hand-rolled lowercase substring containment, which could not
    see a path term's venv-slug spelling and so reported a clean tree while a
    tracked file still carried one. Importing the real predicate is what
    makes the two enforcement surfaces provably agree.
    """
    try:
        from claude_code_hooks_daemon.utils.secret_redaction import term_matches
    except ImportError:
        return _never_matches
    return term_matches


def scan_file(
    path: Path,
    compiled_patterns: list[tuple[dict[str, str], re.Pattern[str]]],
    secret_terms: tuple[str, ...],
    term_matcher: Callable[[str, str], bool],
    scan_root: Path,
) -> list[Violation]:
    """Every violation in one file — public patterns, then the secret list."""
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    violations: list[Violation] = []
    active_terms = [term for term in secret_terms if term]

    # The NAME leaks as loudly as the body. --replace-text never touches a
    # filename, which is why the history rewrite needed --path-rename for
    # three files here; a content-only scanner has the identical blind spot.
    #
    # Checked relative to the SCAN ROOT, never the absolute path: otherwise a
    # checkout that merely lives beneath a directory named after a listed term
    # would flag every file in the tree — an unfixable false positive that
    # would force the whole guard to be switched off.
    #
    # Lexical, with no ``resolve()`` on either side. Both file collections
    # build their paths by joining onto this very root, so a file is always
    # lexically below it and this cannot raise. Resolving would break that:
    # a tracked SYMLINK would resolve to its target and escape the root, and
    # the link's own tracked name — the name that actually ships — is exactly
    # what must be checked. If this ever does raise, the caller passed a
    # mismatched root and FAILING LOUDLY is correct; a fallback here would
    # silently downgrade the scan to basenames and miss directory names.
    relative_name = str(path.relative_to(scan_root))

    for entry, compiled in compiled_patterns:
        name_match = compiled.search(relative_name)
        if name_match:
            pattern_name = entry.get(_PATTERN_KEY_NAME, "unnamed")
            violations.append(
                Violation(
                    file=str(path),
                    line=_FILENAME_LINE,
                    rule=f"{_PUBLIC_RULE_PREFIX}:{pattern_name}",
                    message=(
                        f"FILE NAME matches public pattern '{pattern_name}': "
                        f"{name_match.group(0)}"
                    ),
                )
            )

    for index, term in enumerate(active_terms, start=1):
        if term_matcher(relative_name, term):
            violations.append(
                Violation(
                    file=str(path),
                    line=_FILENAME_LINE,
                    rule=_SECRET_RULE,
                    message=(
                        f"FILE NAME matches a configured blocked term (entry {index} of "
                        f"{len(active_terms)} in the secret word list). The term is "
                        "deliberately not shown."
                    ),
                )
            )

    for number, line in enumerate(content.splitlines(), start=1):
        for entry, compiled in compiled_patterns:
            match = compiled.search(line)
            if match:
                name = entry.get(_PATTERN_KEY_NAME, "unnamed")
                description = entry.get(_PATTERN_KEY_DESCRIPTION, "")
                violations.append(
                    Violation(
                        file=str(path),
                        line=number,
                        rule=f"{_PUBLIC_RULE_PREFIX}:{name}",
                        message=(
                            f"Matches public pattern '{name}'"
                            + (f" ({description})" if description else "")
                            + f": {match.group(0)}"
                        ),
                    )
                )

        for index, term in enumerate(active_terms, start=1):
            # Delegate to the shared predicate — never reimplement the match
            # test here. This loop used to do plain lowercase substring
            # containment, which cannot see a path term's venv-slug spelling
            # ('/home/someone' on disk as 'home_someone'), so the scanner
            # reported a clean tree while a tracked file still carried one.
            if term_matcher(line, term):
                violations.append(
                    Violation(
                        file=str(path),
                        line=number,
                        rule=_SECRET_RULE,
                        message=(
                            f"Matches a configured blocked term (entry {index} of "
                            f"{len(active_terms)} in the secret word list). The term "
                            "is deliberately not shown."
                        ),
                    )
                )
    return violations


def main() -> int:
    args = sys.argv[1:]
    json_mode = "--json" in args
    repo_root = _REPO_ROOT
    config_path = _DEFAULT_CONFIG
    path_override: Path | None = None

    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            path_override = Path(args[index + 1]).resolve()
        if arg == "--config" and index + 1 < len(args):
            config_path = Path(args[index + 1]).resolve()

    if path_override is not None:
        files = sorted(p for p in path_override.rglob("*") if p.is_file())
        scan_root_for_terms = path_override
    else:
        files = _tracked_files(repo_root)
        scan_root_for_terms = repo_root

    public_patterns = load_public_patterns(config_path)
    compiled_patterns = _compile_public_patterns(public_patterns)
    secret_word_list_file = resolve_secret_word_list_file(config_path, scan_root_for_terms)
    secret_terms = resolve_secret_terms(config_path, scan_root_for_terms)

    # Two files are structurally never scan TARGETS, regardless of scan mode:
    # the secret word list itself (gitignored, but --path mode walks the raw
    # filesystem so it must be excluded explicitly too), and the config file
    # that DECLARES the public patterns/secret path — which otherwise matches
    # its own `pattern: '...'` lines against the very patterns it defines.
    excluded = {config_path}
    if secret_word_list_file is not None:
        excluded.add(secret_word_list_file)
    files = [f for f in files if f.resolve() not in excluded]

    exclude_globs = load_exclude_paths(config_path)
    files = filter_excluded_files(files, exclude_globs, scan_root_for_terms)

    # Resolved once, not per file: the predicate is shared with the live
    # handler so both surfaces agree on what counts as a match.
    term_matcher = resolve_term_matcher()

    violations: list[Violation] = []
    for file_path in files:
        violations.extend(
            scan_file(file_path, compiled_patterns, secret_terms, term_matcher, scan_root_for_terms)
        )

    output = {
        "tool": "sensitive_content",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "files_scanned": len(files),
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} sensitive-content violation(s):")
        for violation in violations:
            print(f"  {violation.file}:{violation.line} [{violation.rule}] {violation.message}")
    else:
        print(f"No sensitive-content violations found ({len(files)} files scanned)")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
