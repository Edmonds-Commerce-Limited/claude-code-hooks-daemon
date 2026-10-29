"""Plan 00122 BUG 6 — shell scripts stay compatible with bash 3.2.

Apple ships ``/bin/bash`` 3.2.57 (2007). Any script that runs on a macOS
machine (hook forwarders sourcing ``init.sh``, the skill scripts, the
installer) must avoid bash-4-only constructs or it fails there. The downstream
report flagged this as a latent risk.

This test is the regression guard: it scans every shell script in the repo for
bash-4-only syntax and fails if any appears. Keeping the WHOLE repo bash-3.2
clean (not just the client-facing subset) also lets contributors develop the
daemon on macOS.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories whose .sh/.bash files are scanned. Covers client-facing scripts
# (init.sh, skills, installer, lib) AND dev scripts (qa, release) so the repo
# stays uniformly bash-3.2 clean.
_SCAN_ROOTS = ("scripts", "src")
_TOP_LEVEL_SCRIPTS = ("init.sh",)

# bash-4-only constructs that break under bash 3.2.57 (macOS /bin/bash).
_BASH4_PATTERNS: dict[str, re.Pattern[str]] = {
    "mapfile": re.compile(r"\bmapfile\b"),
    "readarray": re.compile(r"\breadarray\b"),
    "associative array (declare -A)": re.compile(r"\bdeclare\s+-A\b"),
    "associative array (local -A)": re.compile(r"\blocal\s+-A\b"),
    "case-conversion ${v^^}": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\^\^"),
    "case-conversion ${v,,}": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*,,"),
    "case-conversion ${v^}": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\^\}"),
    "case-conversion ${v,}": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*,\}"),
}


def _iter_shell_scripts() -> list[Path]:
    scripts: list[Path] = []
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if base.is_dir():
            scripts.extend(sorted(base.rglob("*.sh")))
            scripts.extend(sorted(base.rglob("*.bash")))
    for name in _TOP_LEVEL_SCRIPTS:
        p = REPO_ROOT / name
        if p.is_file():
            scripts.append(p)
    return scripts


def test_no_bash4_only_constructs_in_shell_scripts() -> None:
    offenders: list[str] = []
    for script in _iter_shell_scripts():
        text = script.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue  # comments are not executed
            for label, pattern in _BASH4_PATTERNS.items():
                if pattern.search(line):
                    rel = script.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {label} -> {stripped}")

    assert (
        not offenders
    ), "bash-4-only constructs found — these break on macOS /bin/bash 3.2.57:\n" + "\n".join(
        offenders
    )


# bash-4-only constructs that are not caught by the patterns above because
# they are options, not syntax: `read -N` (4.0), `read -i` (4.0), `declare -l/-u`,
# `${v@Q}`-style transforms (4.4), `coproc`, `|&` (4.0), `&>>` (4.0), `;&` (4.0).
_BASH4_GENERATED_ONLY: dict[str, re.Pattern[str]] = {
    "read -N": re.compile(r"\bread\b[^\n|;]*\s-[A-Za-z]*N"),
    "read -i": re.compile(r"\bread\b[^\n|;]*\s-[A-Za-z]*i\b"),
    "declare -l/-u": re.compile(r"\b(declare|local|typeset)\s+-[A-Za-z]*[lu]\b"),
    "${v@X} transform": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*@[A-Za-z]\}"),
    "coproc": re.compile(r"\bcoproc\b"),
    "|&": re.compile(r"\|&"),
    "&>>": re.compile(r"&>>"),
    "fallthrough ;&": re.compile(r";;?&"),
}


def _generated_forwarders() -> dict[str, str]:
    """Every forwarder variant the generator can emit: event x relay x nc."""
    from pathlib import Path as _Path

    from claude_code_hooks_daemon.config.models import TransportConfig
    from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

    hooks_dir = REPO_ROOT / ".claude" / "hooks"
    untracked = _Path("/proj/untracked")
    variants: dict[str, str] = {}
    for source in sorted(p for p in hooks_dir.iterdir() if p.is_file()):
        text = source.read_text(encoding="utf-8")
        for relay in (True, False):
            for nc in (True, False):
                transport = TransportConfig(relay_enabled=relay, nc_enabled=nc)
                key = f"{source.name} relay={relay} nc={nc}"
                variants[key] = generate_forwarder_content(
                    text, source.name, transport, untracked, _Path("/proj")
                )
    return variants


def test_generated_forwarders_have_no_bash4_only_constructs() -> None:
    """Forwarders the generator emits run under macOS /bin/bash 3.2 too.

    The checked-in scripts are scanned above; a deployed forwarder is generated
    text, so the guard and fast-path blocks are scanned from the generator's
    output for every event and every relay/nc combination. A static scan is
    used: a real bash 3.2 could not be built on the development host, which has
    neither the C runtime objects nor make.
    """
    variants = _generated_forwarders()
    assert any("relay=True" in key for key in variants)
    offenders: list[str] = []
    for key, text in variants.items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for label, pattern in {**_BASH4_PATTERNS, **_BASH4_GENERATED_ONLY}.items():
                if pattern.search(line):
                    offenders.append(f"{key}:{lineno}: {label} -> {line.strip()}")
    assert not offenders, "bash-4-only constructs in generated forwarders:\n" + "\n".join(offenders)
