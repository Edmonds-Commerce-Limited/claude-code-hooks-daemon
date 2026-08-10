#!/usr/bin/env python3
"""Git-HISTORY sensitive-content sweep — the batch half of the guard (Plan 00202).

``check_sensitive_content.py`` scans the working tree: file contents and file
paths. That is two of the seven surfaces a term can occupy in a repository.
The other five are git METADATA, and none of them is a file, so no tree scan
can ever see them. Cleaning this repository's own history proved it — a blob
rewrite alone left the commit messages, the author identity and the tag
messages untouched:

===================  ==============================  ==================
Surface              git-filter-repo mechanism       Swept here as
===================  ==============================  ==================
Commit messages      ``--replace-message``           ``commit-message``
Author/committer     ``--mailmap``                   ``commit-identity``
Tag names            manual re-tag                   ``ref-name``
Branch names         manual rename                   ``ref-name``
Tag messages         manual re-tag                   ``tag-message``
===================  ==============================  ==================

The ``sensitive_content`` PreToolUse handler blocks these at write time, but a
write-time guard is structurally blind to what is ALREADY committed — every
write-time rule needs a batch equivalent, or everything predating the rule is
permanently unexamined. This is that equivalent.

Same two sources as the handler and the tree scanner, and the same disclosure
rules: public patterns are named with their match; a secret-list match reports
a locator and an entry INDEX only, never the term.

Usage:
    python scripts/qa/check_git_history.py [--json] [--repo DIR] [--config FILE]

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
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "git_history.json"
_DEFAULT_CONFIG: Final[Path] = _REPO_ROOT / ".claude" / "hooks-daemon.yaml"

_TOOL_NAME: Final[str] = "git_history"

_PUBLIC_RULE_PREFIX: Final[str] = "public-pattern"
_SECRET_RULE: Final[str] = "secret-word-list"

_SURFACE_COMMIT_MESSAGE: Final[str] = "commit-message"
_SURFACE_COMMIT_IDENTITY: Final[str] = "commit-identity"
_SURFACE_REF_NAME: Final[str] = "ref-name"
_SURFACE_TAG_MESSAGE: Final[str] = "tag-message"
# Not a git surface: a finding about the CHECKER's own configuration.
_SURFACE_CONFIG: Final[str] = "config"

_PATTERN_KEY_NAME: Final[str] = "name"
_PATTERN_KEY_PATTERN: Final[str] = "pattern"
_PATTERN_KEY_DESCRIPTION: Final[str] = "description"

_OPTION_HISTORY_BASELINE: Final[str] = "history_baseline"
_OPTION_GRANDFATHERED_REFS: Final[str] = "history_grandfathered_refs"

_STALE_GRANDFATHER_RULE: Final[str] = "stale-grandfather"

# ASCII unit/record separators: git format placeholders are interpolated with
# raw user text (commit messages contain newlines, tabs, pipes and quotes), so
# the delimiters must be bytes that cannot occur in that text.
_UNIT_SEPARATOR: Final[str] = "\x1f"
_RECORD_SEPARATOR: Final[str] = "\x1e"

_SHORT_SHA_LENGTH: Final[int] = 8

# `git for-each-ref --format=%(objecttype)`: only an ANNOTATED tag is its own
# object and carries its own message. A branch head and a lightweight tag both
# report "commit", and their %(contents) is the tip commit's message.
_ANNOTATED_TAG_OBJECT_TYPE: Final[str] = "tag"


@dataclass(frozen=True)
class Violation:
    """One flagged occurrence on one metadata surface.

    ``locator`` identifies WHERE without quoting the offending text: a commit
    sha, or a ref name. A ref name can itself be the violation, so it is
    redacted before it is stored — the locator is an output field like any
    other.
    """

    surface: str
    locator: str
    rule: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "locator": self.locator,
            "rule": self.rule,
            "message": self.message,
        }


def _git(repo: Path, *args: str) -> str | None:
    """Run a git command in ``repo``; ``None`` when git itself refuses.

    A non-zero status here means "not a repo", "no such ref", "no refs yet" —
    all legitimately empty rather than errors, and each is reported by the
    CALLER as an absence of data, never as a clean result.
    """
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def is_git_repo(repo: Path) -> bool:
    return repo.is_dir() and _git(repo, "rev-parse", "--git-dir") is not None


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def sensitive_content_options(config_path: Path) -> dict[str, Any]:
    """The SAME config block the handler and the tree scanner read."""
    config = _load_config(config_path)
    handlers = config.get("handlers", {})
    pre_tool_use = handlers.get("pre_tool_use", {}) if isinstance(handlers, dict) else {}
    handler_cfg = (
        pre_tool_use.get("sensitive_content", {}) if isinstance(pre_tool_use, dict) else {}
    )
    options = handler_cfg.get("options", {}) if isinstance(handler_cfg, dict) else {}
    return options if isinstance(options, dict) else {}


def _compile_public_patterns(
    patterns: list[dict[str, str]],
) -> tuple[list[tuple[dict[str, str], re.Pattern[str]]], list[Violation]]:
    """Compiled patterns, plus a violation for each one that would not compile.

    An unparseable pattern is REPORTED, never skipped. The live handler treats
    a bad regex as a documented no-match so one config typo cannot break every
    Write; a QA gate has the opposite obligation — silently dropping a rule
    turns the gate into a blind guard that passes because it stopped looking.
    """
    compiled: list[tuple[dict[str, str], re.Pattern[str]]] = []
    invalid: list[Violation] = []
    for entry in patterns:
        pattern = entry.get(_PATTERN_KEY_PATTERN, "")
        name = entry.get(_PATTERN_KEY_NAME, "unnamed")
        if not pattern:
            continue
        try:
            compiled.append((entry, re.compile(pattern, re.IGNORECASE)))
        except re.error as exc:
            invalid.append(
                Violation(
                    surface=_SURFACE_CONFIG,
                    locator=name,
                    rule=f"{_PUBLIC_RULE_PREFIX}:{name}",
                    message=(
                        f"Public pattern '{name}' is not a valid regex ({exc}) — it "
                        "checked NOTHING. Fix the pattern; a rule that cannot compile "
                        "is a guard that silently stopped guarding."
                    ),
                )
            )
    return compiled, invalid


def _never_matches(_text: str, _term: str) -> bool:
    """Stand-in matcher when the daemon package is not importable.

    ``resolve_secret_terms`` returns an empty tuple in that case, so this is
    never consulted with a real term; it exists so the matcher is always a
    callable and callers need no None-handling.
    """
    return False


def resolve_term_matcher() -> Callable[[str, str], bool]:
    """The shared secret-term predicate — imported, never reimplemented.

    Re-deriving this test is exactly how the 00201 tree scanner came to report
    a clean tree over a contaminated one: its hand-rolled substring check could
    not see a path term's venv-slug spelling.
    """
    try:
        from claude_code_hooks_daemon.utils.secret_redaction import term_matches
    except ImportError:
        return _never_matches
    return term_matches


def _redactor() -> Callable[[str, tuple[str, ...]], str]:
    try:
        from claude_code_hooks_daemon.utils.secret_redaction import redact_text
    except ImportError:
        return lambda text, _terms: text
    return redact_text


def resolve_secret_terms(config_path: Path, repo: Path) -> tuple[str, ...]:
    """Secret-list terms via ``utils/secret_redaction`` — the single source of truth."""
    try:
        from claude_code_hooks_daemon.utils.secret_redaction import (
            load_secret_terms,
            resolve_secret_word_list_path,
        )
    except ImportError:
        return ()

    configured = sensitive_content_options(config_path).get("secret_word_list_path")
    path = resolve_secret_word_list_path(configured if isinstance(configured, str) else None, repo)
    if path is None:
        return ()
    return load_secret_terms(path)


def grandfathered_commits(repo: Path, config_path: Path) -> set[str]:
    """Commits exempted by the declared ``history_baseline``.

    Why this exists: a repository whose history is already contaminated cannot
    be cleaned without a force-push, which only a human may run. A gate that is
    red on the day it lands and stays red until then does not get fixed — it
    gets disabled. The baseline lets the gate enforce "no NEW contamination"
    immediately, and tighten to the whole history once the rewrite lands (drop
    the key).

    FAIL SAFE: an unresolvable baseline exempts NOTHING. A typo'd or
    rewritten-away sha silently exempting the entire history is precisely the
    failure that turns this gate into decoration.
    """
    baseline = sensitive_content_options(config_path).get(_OPTION_HISTORY_BASELINE)
    if not isinstance(baseline, str) or not baseline:
        return set()
    reachable = _git(repo, "rev-list", baseline)
    if reachable is None:
        return set()
    return {line.strip() for line in reachable.splitlines() if line.strip()}


def grandfathered_refs(config_path: Path) -> tuple[str, ...]:
    """Ref names whose EXISTING contamination is tolerated, by exact name.

    Refs cannot be grandfathered by the commit baseline — a ref has no
    ancestry, so exempting by the tagged commit would let a tag created today
    on an ancient commit carry a term into an all-exempt history.

    Unlike the baseline, this list does NOT auto-expire: the same tag names
    survive a history rewrite with cleaned messages, so a forgotten entry would
    exempt them silently forever. ``_stale_grandfather_findings`` therefore
    reports an entry that has become unnecessary — the escape hatch polices its
    own obsolescence rather than trusting anyone to remember.
    """
    configured = sensitive_content_options(config_path).get(_OPTION_GRANDFATHERED_REFS, [])
    if not isinstance(configured, list):
        return ()
    return tuple(name for name in configured if isinstance(name, str) and name)


def _stale_grandfather_findings(
    grandfathered: tuple[str, ...],
    ref_names_seen: set[str],
    suppressed_refs: set[str],
) -> list[Violation]:
    """One finding per grandfather entry that is no longer earning its place.

    Either the ref is gone, or it is now clean. Both mean the exemption is
    dead weight that would silently swallow a NEW leak on that same ref name.
    """
    findings: list[Violation] = []
    for name in grandfathered:
        if name in suppressed_refs:
            continue
        reason = "no longer exists" if name not in ref_names_seen else "is now clean"
        findings.append(
            Violation(
                surface=_SURFACE_REF_NAME,
                locator=name,
                rule=_STALE_GRANDFATHER_RULE,
                message=(
                    f"Grandfather entry '{name}' {reason} — remove it from "
                    f"`{_OPTION_GRANDFATHERED_REFS}`. A stale exemption silently "
                    "swallows any FUTURE leak on that ref."
                ),
            )
        )
    return findings


def _findings(
    text: str,
    surface: str,
    locator: str,
    compiled_patterns: list[tuple[dict[str, str], re.Pattern[str]]],
    secret_terms: tuple[str, ...],
    term_matcher: Callable[[str, str], bool],
) -> list[Violation]:
    """Every violation in one piece of metadata."""
    violations: list[Violation] = []

    for entry, compiled in compiled_patterns:
        match = compiled.search(text)
        if match:
            name = entry.get(_PATTERN_KEY_NAME, "unnamed")
            description = entry.get(_PATTERN_KEY_DESCRIPTION, "")
            violations.append(
                Violation(
                    surface=surface,
                    locator=locator,
                    rule=f"{_PUBLIC_RULE_PREFIX}:{name}",
                    message=(
                        f"Matches public pattern '{name}'"
                        + (f" ({description})" if description else "")
                        + f": {match.group(0)}"
                    ),
                )
            )

    for index, term in enumerate(secret_terms, start=1):
        if term_matcher(text, term):
            violations.append(
                Violation(
                    surface=surface,
                    locator=locator,
                    rule=_SECRET_RULE,
                    message=(
                        f"Matches a configured blocked term (entry {index} of "
                        f"{len(secret_terms)} in the secret word list). The term is "
                        "deliberately not shown."
                    ),
                )
            )
    return violations


def _commit_records(repo: Path, exempt: set[str]) -> list[tuple[str, str, str]]:
    """``(sha, message, identity)`` for every commit not grandfathered.

    ``--all`` rather than HEAD: a term on an unmerged branch is published the
    moment that branch is pushed.
    """
    raw = _git(
        repo,
        "log",
        "--all",
        f"--format=%H{_UNIT_SEPARATOR}%B{_UNIT_SEPARATOR}%an %ae %cn %ce{_RECORD_SEPARATOR}",
    )
    if raw is None:
        return []

    records: list[tuple[str, str, str]] = []
    for chunk in raw.split(_RECORD_SEPARATOR):
        fields = chunk.split(_UNIT_SEPARATOR)
        if len(fields) < 3:
            continue
        sha = fields[0].strip()
        if not sha or sha in exempt:
            continue
        records.append((sha, fields[1], fields[2]))
    return records


def _ref_records(repo: Path) -> list[tuple[str, str]]:
    """``(ref_name, annotation)`` for every branch, tag and remote-tracking ref.

    ``refs/remotes`` is included because a remote branch NAME is the most
    published surface there is — readable by anyone with access to the origin.
    The commit sweep already reaches it via ``git log --all``; enumerating only
    ``refs/heads``/``refs/tags`` here left the name half of that surface blind,
    so a term in a pushed branch name passed while the gate reported clean.

    Refs are NEVER grandfathered by the commit baseline. A ref has no ancestry
    of its own, so a tag created today on a decade-old commit would otherwise
    be exempt — a fresh name carrying a term into an all-grandfathered history.

    ``annotation`` is the tag's OWN message and is empty for anything that does
    not have one. ``%(contents)`` is a trap here: for a branch head, and for a
    LIGHTWEIGHT tag, it returns the tip commit's message — so scanning it
    blindly re-reports every commit message a second time under the wrong
    surface AND launders it past the baseline exemption, since a ref is never
    grandfathered. Only ``%(objecttype) == "tag"`` (an annotated tag) has a
    message of its own; everything else is already covered by the commit sweep.
    """
    raw = _git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)"
        + _UNIT_SEPARATOR
        + "%(objecttype)"
        + _UNIT_SEPARATOR
        + "%(contents)"
        + _RECORD_SEPARATOR,
        "refs/heads",
        "refs/tags",
        "refs/remotes",
    )
    if raw is None:
        return []

    records: list[tuple[str, str]] = []
    for chunk in raw.split(_RECORD_SEPARATOR):
        fields = chunk.split(_UNIT_SEPARATOR)
        if len(fields) < 3:
            continue
        name = fields[0].strip()
        if not name:
            continue
        annotation = fields[2] if fields[1].strip() == _ANNOTATED_TAG_OBJECT_TYPE else ""
        records.append((name, annotation))
    return records


def sweep(
    repo: Path,
    compiled_patterns: list[tuple[dict[str, str], re.Pattern[str]]],
    secret_terms: tuple[str, ...],
    term_matcher: Callable[[str, str], bool],
    exempt: set[str],
    grandfathered: tuple[str, ...] = (),
) -> tuple[list[Violation], int, int]:
    """All violations across every git metadata surface, plus what was scanned."""
    redact = _redactor()
    violations: list[Violation] = []

    commits = _commit_records(repo, exempt)
    for sha, message, identity in commits:
        short = sha[:_SHORT_SHA_LENGTH]
        violations.extend(
            _findings(
                message,
                _SURFACE_COMMIT_MESSAGE,
                short,
                compiled_patterns,
                secret_terms,
                term_matcher,
            )
        )
        violations.extend(
            _findings(
                identity,
                _SURFACE_COMMIT_IDENTITY,
                short,
                compiled_patterns,
                secret_terms,
                term_matcher,
            )
        )

    refs = _ref_records(repo)
    ref_names_seen: set[str] = set()
    suppressed_refs: set[str] = set()
    for name, contents in refs:
        ref_names_seen.add(name)
        # The ref NAME is both the locator and a thing that can match, so it is
        # redacted before being stored — otherwise the report announcing the
        # leak would republish it, the same defect the handler's deny reason
        # had to fix.
        safe_name = redact(name, secret_terms)
        ref_findings = _findings(
            name, _SURFACE_REF_NAME, safe_name, compiled_patterns, secret_terms, term_matcher
        ) + _findings(
            contents, _SURFACE_TAG_MESSAGE, safe_name, compiled_patterns, secret_terms, term_matcher
        )
        if not ref_findings:
            continue
        if name in grandfathered:
            suppressed_refs.add(name)
            continue
        violations.extend(ref_findings)

    violations.extend(_stale_grandfather_findings(grandfathered, ref_names_seen, suppressed_refs))

    return violations, len(commits), len(refs)


def main() -> int:
    args = sys.argv[1:]
    json_mode = "--json" in args
    repo = _REPO_ROOT
    config_path = _DEFAULT_CONFIG

    for index, arg in enumerate(args):
        if arg == "--repo" and index + 1 < len(args):
            repo = Path(args[index + 1]).resolve()
        if arg == "--config" and index + 1 < len(args):
            config_path = Path(args[index + 1]).resolve()

    violations: list[Violation] = []
    commits_scanned = 0
    refs_scanned = 0
    repo_present = is_git_repo(repo)

    if repo_present:
        compiled_patterns, invalid_patterns = _compile_public_patterns(
            _public_patterns(config_path)
        )
        secret_terms = resolve_secret_terms(config_path, repo)
        violations, commits_scanned, refs_scanned = sweep(
            repo,
            compiled_patterns,
            secret_terms,
            resolve_term_matcher(),
            grandfathered_commits(repo, config_path),
            grandfathered_refs(config_path),
        )
        violations = invalid_patterns + violations

    output = {
        "tool": _TOOL_NAME,
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "commits_scanned": commits_scanned,
            "refs_scanned": refs_scanned,
            "is_git_repo": repo_present,
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} git-history violation(s):")
        for violation in violations:
            print(
                f"  [{violation.surface}] {violation.locator} "
                f"[{violation.rule}] {violation.message}"
            )
    elif not repo_present:
        print(f"Not a git repository, nothing to sweep: {repo}")
    else:
        print(
            f"No git-history violations found "
            f"({commits_scanned} commits, {refs_scanned} refs scanned)"
        )

    return 1 if violations else 0


def _public_patterns(config_path: Path) -> list[dict[str, str]]:
    patterns = sensitive_content_options(config_path).get("public_patterns", [])
    return patterns if isinstance(patterns, list) else []


if __name__ == "__main__":
    sys.exit(main())
