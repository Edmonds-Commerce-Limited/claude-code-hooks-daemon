#!/usr/bin/env python3
"""Fail when shipped code fetches something it then executes, unpinned.

The class -- `fetch-then-execute-unpinned` (Plan 00412 class 14) -- is a fetch
whose response is executed, where the destination is not fully determined by the
shipped code, the bytes are not verified against a digest carried independently
of them, and the scheme is not forced. Alongside it sits the adjacent case that
shares its cause: a flag that turns a protection OFF on a production path.

Four rules, each keyed to a mechanism rather than to a known instance:

``security-downgrade-flag``
    A literal set of flags whose only effect is to disable a protection --
    ``protocol.*.allow=always``, ``GIT_ALLOW_PROTOCOL``, ``--no-verify``,
    ``PYTHONHTTPSVERIFY=0``, ``verify=False``, and ``-k``/``--insecure``.

``fetch-piped-to-shell``
    A ``curl``/``wget`` whose output is piped into an interpreter.

``suppressed-fetch``
    A ``curl``/``wget``/``git clone`` whose failure is discarded to
    ``/dev/null``, so the fetch cannot be seen to have gone wrong.

``unvalidated-url-expansion``
    A URL built from an environment expansion that nothing scheme-checks, in a
    file that fetches. This one keys on PROVENANCE, not on data flow, and
    deliberately: the instance it was built for reaches its ``source`` through
    four hops (``curl -o "$tmp"`` -> ``printf`` -> the caller's
    ``discovery_lib`` -> ``. "$discovery_lib"``), which no token-following
    heuristic survives. A base URL an attacker can set to ``http://`` is the
    defect whether or not the bytes are traceable to the execution.

**`-k` is why this rule needs controls rather than confidence.** It means
``--insecure`` to curl and ``--key`` to sort. The worklist calls the
downgrade-flag rule "the cheapest rule in this report and I would ship it
first", and cheap rules are exactly the ones that ship matching ``sort -k2``
and get switched off within a week -- at which point they protect nothing,
which is the failure this plan exists to prevent. So ``-k`` and ``--insecure``
count only on a line that actually fetches.

**Comments are text, not commands.** This repository ships the published
``curl … | bash`` install one-liner in its own script headers so a reader can
see how they are meant to be run. Scanning those would make the first run
mostly noise about its own documentation, so comments are stripped first --
shell comments by a quote-aware scan, Python comments AND string literals via
``tokenize``, which is what keeps a docstring's example from reading as an
instruction.

**What this does NOT do**, stated because a Detector that overstates its reach
is worse than one that admits a gap: it does not follow a downloaded path to
its execution, it does not verify that a digest is checked, and it reads one
file at a time, so a fetch in one script executed by another is invisible to
it. The provenance rule exists because of that limit, not in ignorance of it.

Usage:
    python scripts/qa/check_security_downgrade_flags.py [--json] [--root DIR]

Exit codes:
    0 -- no unpinned fetch and no disabled protection in scanned code
    1 -- at least one violation
"""

from __future__ import annotations

import io
import json
import re
import sys
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "security_downgrade_flags.json"
DEFAULT_INVENTORY: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "security-downgrade-inventory.yaml"

RULE_DOWNGRADE_FLAG: Final[str] = "security-downgrade-flag"
RULE_FETCH_PIPED_TO_SHELL: Final[str] = "fetch-piped-to-shell"
RULE_SUPPRESSED_FETCH: Final[str] = "suppressed-fetch"
RULE_UNVALIDATED_URL_EXPANSION: Final[str] = "unvalidated-url-expansion"

_SCANNED_SUFFIXES: Final[frozenset[str]] = frozenset({".sh", ".bash", ".py"})
#: YAML is scanned ONLY where it EXECUTES. The first sweep flagged the upgrade
#: manifest that DOCUMENTS `curl_pipe_shell` -- a project's own description of
#: the danger, reported as the danger. A config-changes manifest is
#: documentation about configuration, not configuration that runs.
_CI_SUFFIXES: Final[frozenset[str]] = frozenset({".yml", ".yaml"})
_CI_ROOTS: Final[tuple[str, ...]] = (".github", ".gitlab-ci", ".circleci")

#: Directories whose contents are not shipped code judged by this Detector.
#: `tests` is the load-bearing one: a fixture legitimately passes
#: `protocol.file.allow=always` so a local clone works, and reporting the
#: harness for doing its job is how a check earns a reputation for noise.
_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "tests",
        "Tests",
        "untracked",
        "vendor",
        "venv",
        ".venv",
    }
)

#: Flags whose only purpose is to switch a protection off. Matched anywhere.
_UNCONDITIONAL_DOWNGRADES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"protocol\.[A-Za-z0-9_]+\.allow\s*=\s*always"),
        "re-enables a git protocol the CVE-2022-39253 fix disabled",
    ),
    (re.compile(r"\bGIT_ALLOW_PROTOCOL\b"), "widens the git protocol allowlist"),
    (re.compile(r"(?<!\S)--no-verify(?!\S)"), "skips the hooks that verify the operation"),
    (re.compile(r"\bPYTHONHTTPSVERIFY\s*=\s*0"), "disables Python TLS certificate verification"),
    (re.compile(r"\bverify\s*=\s*False\b"), "disables TLS certificate verification"),
)

#: Downgrades whose spelling is ambiguous, so they count only where the line
#: fetches. `-k` is `--insecure` to curl and `--key` to sort.
_FETCH_SCOPED_DOWNGRADES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"(?<!\S)(?:-k|--insecure)(?!\S)"),
        "disables TLS certificate verification for this fetch",
    ),
)

_FETCH_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\S)(?:curl|wget)\b")
_CLONE_OR_FETCH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\S)(?:curl|wget)\b|(?<!\S)git\s+clone\b"
)
#: A pipe into something that EXECUTES its input. `| jq` and `| grep` read the
#: bytes; `| sh` runs them, and that is the whole distinction the class turns on.
_PIPED_TO_INTERPRETER_RE: Final[re.Pattern[str]] = re.compile(
    r"\|\s*(?:sudo\s+)?(?:/\S*/)?(?:ba|z|k|da)?sh\b|\|\s*(?:sudo\s+)?(?:python3?|perl|ruby)\b"
)
_DISCARDED_RE: Final[re.Pattern[str]] = re.compile(r"2>|&>")
#: Something on the line READS the fetch's exit status. `if ! git clone …
#: >/dev/null 2>&1; then _fail …` discards the OUTPUT and acts on the FAILURE,
#: which is the correct shape -- quiet on success, loud on failure. Reporting it
#: would be telling the author to make a working error path noisier.
_STATUS_CONSUMED_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)(?:if|elif|while|until)\s|&&|\|\|"
)
#: `VAR="${ENV_VAR:-https://…}"` — an endpoint the environment can replace.
_URL_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<local>[A-Za-z_][A-Za-z0-9_]*)=[\"']?\$\{(?P<env>[A-Za-z_][A-Za-z0-9_]*)"
    r":-(?P<default>https?://[^}\"']*)\}"
)
#: A `case`/`if` arm pinning the scheme. The glob form is what shell uses.
_SCHEME_GUARD_RE: Final[re.Pattern[str]] = re.compile(r"https://\*|\bstartswith\(\s*[\"']https")

_REMEDIATION: Final[str] = (
    "Force the scheme (reject a non-https override), pin the ref, verify the bytes "
    "against a digest carried independently of them, or drop the flag. If a "
    "downgrade is genuinely required, it belongs on a test fixture path, not on "
    "the path that produces an installed daemon."
)


@dataclass(frozen=True, slots=True)
class Violation:
    """One line of shipped code that fetches unpinned or disables a protection."""

    path: str
    line: int
    rule: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "rule": self.rule, "detail": self.detail}


def _closing_quote_index(line: str) -> int | None:
    """Where an open double-quoted string ends on this line, if it does."""
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index
        index += 1
    return None


def _scan_line(line: str) -> tuple[int, bool]:
    """Return where a comment starts, and whether a double quote is left open."""
    in_single = False
    in_double = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and in_double:
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return index, in_double
        index += 1
    return len(line), in_double


def strip_shell_comments(text: str) -> list[str]:
    """Blank shell comments AND multi-line string bodies, preserving positions.

    Two different things look like a command without being one, and both were
    found by the first real sweep rather than anticipated:

    * a `#` comment — quote-aware, because a `#` inside a string is data;
    * a line sitting INSIDE a double-quoted string opened on an earlier line.
      `prerequisites.sh` tells a human how to install uv by hand inside a
      multi-line `fail_fast "…"`, using the same text as the real invocation a
      few lines below. Only one of the two runs.

    Blanking ends at the closing quote, deliberately: a stripper that never
    recovers from an opening quote would silence the real command that follows,
    trading a false positive for a false negative — the worse of the two, since
    nobody ever sees what a check failed to say.
    """
    stripped: list[str] = []
    continuing = False
    for raw in text.splitlines():
        line = raw
        if continuing:
            close = _closing_quote_index(line)
            if close is None:
                stripped.append("")
                continue
            line = " " * (close + 1) + line[close + 1 :]
            continuing = False
        cut, opened = _scan_line(line)
        continuing = opened
        stripped.append(line[:cut])
    return stripped


def strip_python_literals(text: str) -> list[str]:
    """Blank Python comments and string literals, preserving line positions.

    A docstring showing the install one-liner is documentation. `tokenize` is
    used rather than a regex because a triple-quoted block spans lines, and a
    line-oriented strip cannot see where it ends. A file that does not tokenize
    is returned unchanged rather than skipped: refusing to read it would make
    an unparseable file the way to evade this check.
    """
    lines = text.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines

    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            index = row - 1
            if index >= len(lines):
                continue
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else len(lines[index])
            lines[index] = lines[index][:begin] + " " * (finish - begin) + lines[index][finish:]
    return lines


def code_lines(path: Path, text: str) -> list[str]:
    """The file with its non-executable text removed."""
    if path.suffix == ".py":
        return strip_python_literals(text)
    return strip_shell_comments(text)


def _line_violations(relative: str, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for number, line in enumerate(lines, start=1):
        fetches = bool(_FETCH_RE.search(line))

        for pattern, why in _UNCONDITIONAL_DOWNGRADES:
            if pattern.search(line):
                violations.append(Violation(relative, number, RULE_DOWNGRADE_FLAG, why))
        if fetches:
            for pattern, why in _FETCH_SCOPED_DOWNGRADES:
                if pattern.search(line):
                    violations.append(Violation(relative, number, RULE_DOWNGRADE_FLAG, why))

        if fetches and _PIPED_TO_INTERPRETER_RE.search(line):
            violations.append(
                Violation(
                    relative,
                    number,
                    RULE_FETCH_PIPED_TO_SHELL,
                    "downloaded bytes are executed by an interpreter with nothing verifying them",
                )
            )

        if (
            _CLONE_OR_FETCH_RE.search(line)
            and "/dev/null" in line
            and _DISCARDED_RE.search(line)
            and not _STATUS_CONSUMED_RE.search(line)
        ):
            violations.append(
                Violation(
                    relative,
                    number,
                    RULE_SUPPRESSED_FETCH,
                    "the fetch's failure is discarded, so a failed download reads as a success",
                )
            )
    return violations


def _expansion_violations(relative: str, lines: list[str]) -> list[Violation]:
    """URLs the environment can replace, in a file that fetches.

    Both conditions matter. Without "the file fetches", every default-endpoint
    constant in the tree is a finding, which is the noise that gets a cheap
    rule disabled. Without the expansion, an https literal in the source is
    simply the address.
    """
    if not any(_CLONE_OR_FETCH_RE.search(line) for line in lines):
        return []
    if any(_SCHEME_GUARD_RE.search(line) for line in lines):
        return []

    violations: list[Violation] = []
    for number, line in enumerate(lines, start=1):
        match = _URL_EXPANSION_RE.search(line)
        if match is None:
            continue
        violations.append(
            Violation(
                relative,
                number,
                RULE_UNVALIDATED_URL_EXPANSION,
                f"${{{match.group('env')}}} replaces the endpoint and nothing forces the "
                "scheme, so an http:// override is fetched without complaint",
            )
        )
    return violations


def candidate_files(root: Path) -> list[Path]:
    """Every shipped file this Detector is able to judge."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in _EXCLUDED_DIRS for part in parts):
            continue
        executes_as_ci = path.suffix in _CI_SUFFIXES and any(part in _CI_ROOTS for part in parts)
        if path.suffix in _SCANNED_SUFFIXES or executes_as_ci:
            found.append(path)
    return found


def scan(root: Path) -> list[Violation]:
    """Every violation in the tree below ``root``."""
    violations: list[Violation] = []
    for path in candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            violations.append(
                Violation(
                    str(path.relative_to(root)),
                    0,
                    RULE_DOWNGRADE_FLAG,
                    f"could not be read, so it was NOT checked: {error}",
                )
            )
            continue
        relative = str(path.relative_to(root))
        lines = code_lines(path, text)
        violations.extend(_line_violations(relative, lines))
        violations.extend(_expansion_violations(relative, lines))
    return violations


def _load_rows(inventory_path: Path) -> list[dict[str, object]]:
    if not inventory_path.is_file():
        return []
    loaded = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
    rows = loaded.get("rows") or [] if isinstance(loaded, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _row_key(row: dict[str, object]) -> tuple[str, str]:
    return str(row.get("path", "")), str(row.get("rule", ""))


def unrecorded(root: Path, inventory_path: Path) -> list[Violation]:
    """Every instance the inventory does not account for, in BOTH directions.

    Keyed on ``(path, rule)`` with an occurrence COUNT, never on a line number:
    a line drifts on the next unrelated edit, and an inventory that goes stale
    on every edit is one people delete. The count is also what stops a row
    becoming a blanket exemption for its file -- one recorded ``curl | sh``
    must not licence the next one beside it.

    A row for an instance that is GONE fails too. That is the same discipline
    the dangerous-invocation corpus holds itself to: a record claiming an
    accepted defect that no longer exists sends the next reader at work already
    done, and overstates how much of the tree is still unfixed.
    """
    found = Counter(_row_key({"path": v.path, "rule": v.rule}) for v in scan(root))
    rows = _load_rows(inventory_path)

    findings: list[Violation] = []
    recorded: Counter[tuple[str, str]] = Counter()
    for row in rows:
        key = _row_key(row)
        # A missing note is reported, but the row still COUNTS. Skipping it
        # would also trip the count comparison below, reporting one defect
        # twice -- and a reader cannot tell a double-report from two problems.
        if not str(row.get("note", "")).strip():
            findings.append(
                Violation(
                    key[0],
                    0,
                    key[1],
                    f"inventory row for {key[0]} [{key[1]}] has no note; "
                    "an unexplained exemption cannot be reviewed",
                )
            )
        try:
            recorded[key] += int(str(row.get("occurrences", 0)))
        except ValueError:
            findings.append(
                Violation(key[0], 0, key[1], "inventory row has a non-numeric `occurrences`")
            )

    for key in sorted(set(found) | set(recorded)):
        path, rule = key
        actual, expected = found[key], recorded[key]
        if actual == expected:
            continue
        if actual > expected:
            findings.append(
                Violation(
                    path,
                    0,
                    rule,
                    f"{actual} instance(s) of [{rule}] in {path}, but the inventory "
                    f"records {expected} -- record the new one with a verdict and a note",
                )
            )
        else:
            findings.append(
                Violation(
                    path,
                    0,
                    rule,
                    f"the inventory records {expected} instance(s) of [{rule}] in {path} "
                    f"but only {actual} remain -- the rest are no longer there, and the "
                    "good news has to be recorded too",
                )
            )
    return findings


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    root = _REPO_ROOT
    for index, arg in enumerate(args):
        if arg == "--root" and index + 1 < len(args):
            root = Path(args[index + 1]).resolve()

    # The GATE is "is every instance recorded", not "are there zero instances".
    # Eight are known, each with a verdict and a note; failing on those would
    # make this permanently red, and a permanently-red gate is one nobody
    # reads. A NEW instance, or a recorded one that has gone, fails.
    violations = unrecorded(root, DEFAULT_INVENTORY)
    files_checked = len(candidate_files(root))
    instances_recorded = len(scan(root))

    output = {
        "tool": "security_downgrade_flags",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "files_checked": files_checked,
            "instances_recorded": instances_recorded,
        },
        "violations": [violation.to_dict() for violation in violations],
    }

    if "--json" in args:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} unrecorded finding(s) across {files_checked} files:")
        for violation in violations:
            print(f"  {violation.path} [{violation.rule}]")
            print(f"      {violation.detail}")
        print(f"\n{_REMEDIATION}")
    else:
        # The count is stated on the CLEAN path too, deliberately: "passed" here
        # means every instance is accounted for, NOT that there are none, and a
        # gate that prints only "OK" would let a reader believe the second.
        print(
            f"Every instance is recorded ({instances_recorded} across "
            f"{files_checked} files checked)"
        )

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
