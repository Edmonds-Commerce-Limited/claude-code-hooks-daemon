#!/usr/bin/env python3
"""Fail when agent-facing guidance names an unset shell variable (Plan 00192).

Guidance under ``src/`` used to tell agents to run::

    $PYTHON -m claude_code_hooks_daemon.daemon.cli <subcommand>

``$PYTHON`` is never set in an agent's shell — it exists only inside the process
scope of the wrapper scripts that source ``_resolve-venv.sh``, and ``init.sh``
deliberately does NOT export its ``PYTHON_CMD``. The PATH ``python3`` cannot
import the package either, because the venv sets
``include-system-site-packages = false``.

So every documented line expanded to ``-m claude_code_hooks_daemon...`` and bash
reported ``-m: command not found`` (exit 127) — an error naming neither Python,
the venv, nor the daemon. Agents concluded the package was uninstalled and
damaged working installations trying to reinstall it.

The replacement is ``utils.cli_command.daemon_cli_command()``, which emits an
absolute path to the deployed ``bin/hooks-daemon`` wrapper. This check exists so
the old pattern cannot creep back in.

Usage:
    python scripts/qa/check_python_var_guidance.py [--json] [--path DIR]

Exit codes:
    0 — no violations
    1 — at least one violation
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "python_var_guidance.json"

_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src"

#: The banned pattern: a literal ``$PYTHON`` shell variable reference.
_BANNED_PATTERN: Final[re.Pattern[str]] = re.compile(r"\$\{?PYTHON\}?\b")

#: File suffixes that reach agents — Python source that builds guidance strings,
#: and markdown shipped into client projects.
_SCANNED_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".md"})

#: Paths exempt from the rule, relative to the repo root.
#:
#: ``templates/hooks-daemon`` and the skill wrappers legitimately SET and use
#: ``PYTHON`` internally — they are the scripts that resolve it. The rule targets
#: guidance that tells a READER to use a variable they never received.
#: ``utils/cli_command.py`` is the module that REPLACES the pattern; its
#: docstring necessarily quotes it to explain what it fixes — mirroring how
#: ``check_canonical_callers.sh`` exempts ``resolve_venv.sh`` because that file
#: IS the resolver.
_EXEMPT_SUBPATHS: Final[tuple[str, ...]] = (
    "src/claude_code_hooks_daemon/install/templates/hooks-daemon",
    "src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/",
    "src/claude_code_hooks_daemon/utils/cli_command.py",
)

#: Inline escape hatch for a genuine exception, recorded in-place.
_EXEMPT_MARKER: Final[str] = "python-var-guidance-exempt:"

_RULE_NAME: Final[str] = "unset-shell-variable-in-guidance"

_REMEDIATION: Final[str] = (
    "Use utils.cli_command.daemon_cli_command(...) so the emitted command is an "
    "absolute path to the deployed bin/hooks-daemon wrapper. In static markdown, "
    "write the wrapper path directly."
)


@dataclass(frozen=True)
class Violation:
    """A single banned occurrence."""

    file: str
    line: int
    rule: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
        }


def _is_exempt_path(path: Path) -> bool:
    try:
        relative = path.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        relative = path.as_posix()
    return any(relative.startswith(prefix) for prefix in _EXEMPT_SUBPATHS)


def scan_file(path: Path) -> list[Violation]:
    """Return every banned occurrence in ``path``."""
    if _is_exempt_path(path):
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    violations: list[Violation] = []
    for number, line in enumerate(content.splitlines(), start=1):
        if _EXEMPT_MARKER in line:
            continue
        if _BANNED_PATTERN.search(line):
            violations.append(
                Violation(
                    file=str(path),
                    line=number,
                    rule=_RULE_NAME,
                    message=(
                        "Agent-facing guidance references $PYTHON, which is never set "
                        f"in an agent's shell. {_REMEDIATION}"
                    ),
                )
            )
    return violations


def scan_tree(root: Path) -> list[Violation]:
    """Recursively scan ``root`` for banned occurrences."""
    violations: list[Violation] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
            continue
        violations.extend(scan_file(path))
    return violations


def main() -> int:
    json_mode = "--json" in sys.argv
    scan_root = _DEFAULT_SCAN_ROOT
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            scan_root = Path(args[index + 1]).resolve()

    violations = scan_tree(scan_root)

    output = {
        "tool": "python_var_guidance",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} $PYTHON guidance violations:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}")
        print(f"\n{_REMEDIATION}")
    else:
        print("No $PYTHON guidance violations found")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
