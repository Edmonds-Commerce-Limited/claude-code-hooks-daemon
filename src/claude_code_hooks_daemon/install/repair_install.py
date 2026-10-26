"""Terminal-runnable repair of a broken hooks install (Plan 00552 Task 3.1).

A merge, rebase or stash pop can leave conflict markers in the files the
daemon owns: the hook stubs in ``.claude/hooks/``, ``.claude/init.sh`` and
``.claude/settings.json``. A stub that cannot parse exits 2, which Claude
Code reads as a block, so the session cannot take a prompt and cannot run a
repair itself. This module needs no session, no running daemon and no venv
build: it redeploys the stubs and ``init.sh`` from the installed daemon's
templates through the installer's own generator, and checks every file.

``settings.json`` is only ever checked here. Rewriting it is the explicit,
human-chosen ``--reconcile-settings`` step (Plan 00175), and a file carrying
conflict markers is never rewritten at all.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import get_untracked_dir
from claude_code_hooks_daemon.install.forwarder_generator import (
    generate_forwarder_content,
    load_transport_config,
)

CONFLICT_MARKER_PREFIXES: Final[tuple[str, ...]] = ("<<<<<<<", "=======", ">>>>>>>")

_CLAUDE_DIR: Final[str] = ".claude"
_HOOKS_DIR: Final[str] = "hooks"
_INIT_SH: Final[str] = "init.sh"
_SETTINGS_JSON: Final[str] = "settings.json"
_EXEC_BITS: Final[int] = 0o111
_BASH_SYNTAX_TIMEOUT_SECONDS: Final[int] = Timeout.REQUEST_DEFAULT


@dataclass
class InstallRepairReport:
    """What a repair (or ``--check``) found and did, as project-relative paths."""

    ok: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    redeployed: list[str] = field(default_factory=list)
    would_redeploy: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    settings_conflicted: bool = False

    @property
    def clean(self) -> bool:
        """True when nothing is broken (and, in check mode, nothing would change)."""
        return not self.broken and not self.would_redeploy


def has_conflict_markers(text: str) -> bool:
    """True when any line of ``text`` starts with a git conflict marker."""
    return any(line.startswith(CONFLICT_MARKER_PREFIXES) for line in text.splitlines())


def bash_syntax_error(path: Path) -> str | None:
    """Run ``bash -n`` on ``path``; return the diagnostic, or None when it parses."""
    bash = shutil.which("bash")
    if bash is None:
        raise FileNotFoundError("bash is required to check the hook scripts but is not on PATH")
    try:
        result = subprocess.run(  # nosec B603 - fixed argv, path is a project file
            [bash, "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=_BASH_SYNTAX_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"bash -n did not finish within {_BASH_SYNTAX_TIMEOUT_SECONDS} seconds"
    if result.returncode == 0:
        return None
    return result.stderr.strip() or f"bash -n exited {result.returncode}"


def _relative(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | _EXEC_BITS)


def _write_if_different(path: Path, content: str, *, check: bool) -> bool:
    """Write ``content`` unless identical; True when a write is (or would be) needed."""
    if path.is_file() and path.read_text() == content:
        return False
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _make_executable(path)
    return True


def _redeploy_stubs(
    project_root: Path, daemon_dir: Path, report: InstallRepairReport, *, check: bool
) -> None:
    source_hooks = daemon_dir / _CLAUDE_DIR / _HOOKS_DIR
    if not source_hooks.is_dir():
        raise FileNotFoundError(f"Installed daemon's hook templates not found: {source_hooks}")
    transport = load_transport_config(project_root)
    untracked_dir = get_untracked_dir(project_root)
    for source in sorted(source_hooks.iterdir()):
        if not source.is_file() or source.name.startswith("."):
            continue
        target = project_root / _CLAUDE_DIR / _HOOKS_DIR / source.name
        content = generate_forwarder_content(
            source.read_text(), source.name, transport, untracked_dir, project_root
        )
        if _write_if_different(target, content, check=check):
            bucket = report.would_redeploy if check else report.redeployed
            bucket.append(_relative(target, project_root))


def _redeploy_init_sh(
    project_root: Path, daemon_dir: Path, report: InstallRepairReport, *, check: bool
) -> None:
    source = daemon_dir / _INIT_SH
    if not source.is_file():
        raise FileNotFoundError(f"Installed daemon's init.sh not found: {source}")
    target = project_root / _CLAUDE_DIR / _INIT_SH
    if _write_if_different(target, source.read_text(), check=check):
        bucket = report.would_redeploy if check else report.redeployed
        bucket.append(_relative(target, project_root))


def _check_scripts(project_root: Path, report: InstallRepairReport) -> None:
    scripts = [project_root / _CLAUDE_DIR / _INIT_SH]
    hooks_dir = project_root / _CLAUDE_DIR / _HOOKS_DIR
    if hooks_dir.is_dir():
        scripts.extend(
            p for p in sorted(hooks_dir.iterdir()) if p.is_file() and not p.name.startswith(".")
        )
    for script in scripts:
        name = _relative(script, project_root)
        if not script.is_file():
            report.broken.append(name)
            report.notes.append(f"{name}: missing")
            continue
        error = bash_syntax_error(script)
        if error is None:
            report.ok.append(name)
        else:
            report.broken.append(name)
            report.notes.append(f"{name}: {error}")


def _check_settings(project_root: Path, report: InstallRepairReport) -> bool:
    """Report on settings.json; True when it parses as a JSON object."""
    path = project_root / _CLAUDE_DIR / _SETTINGS_JSON
    name = _relative(path, project_root)
    if not path.is_file():
        report.broken.append(name)
        report.notes.append(f"{name}: missing")
        return False
    text = path.read_text()
    if has_conflict_markers(text):
        report.broken.append(name)
        report.settings_conflicted = True
        report.notes.append(
            f"{name}: carries merge conflict markers; it is never overwritten. "
            "Resolve it by hand (keep both sides' entries), then run this command again"
        )
        return False
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        report.broken.append(name)
        report.notes.append(f"{name}: not valid JSON: {exc}")
        return False
    if not isinstance(loaded, dict):
        report.broken.append(name)
        report.notes.append(f"{name}: not a JSON object")
        return False
    report.ok.append(name)
    return True


def repair_install(project_root: Path, *, check: bool) -> InstallRepairReport:
    """Redeploy the hook stubs and ``init.sh``, then check every file.

    In a self-install the tracked stubs ARE the templates, so nothing is
    redeployed; the files are only checked.

    Args:
        project_root: The client project root.
        check: Report only; write nothing.

    Returns:
        The report. ``report.clean`` is False while anything is broken.

    Raises:
        FileNotFoundError: If the installed daemon's templates are missing.
    """
    project_root = project_root.resolve()
    report = InstallRepairReport()
    daemon_dir = get_untracked_dir(project_root).parent
    if daemon_dir.resolve() != project_root:
        _redeploy_stubs(project_root, daemon_dir, report, check=check)
        _redeploy_init_sh(project_root, daemon_dir, report, check=check)
    else:
        report.notes.append(
            "self-install: hooks and init.sh are the tracked templates; not redeployed"
        )
    _check_scripts(project_root, report)
    _check_settings(project_root, report)
    return report


def settings_path(project_root: Path) -> Path:
    """The project's ``.claude/settings.json``."""
    return project_root / _CLAUDE_DIR / _SETTINGS_JSON
