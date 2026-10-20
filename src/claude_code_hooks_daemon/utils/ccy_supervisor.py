"""Shared ccy-supervisor liveness and arming helpers (Plan 00283).

Pure functions extracted from ``ccy_supervisor_integrity`` so that the
SessionStart integrity handler and the ``standing_authorisations`` channel
router share ONE implementation of "is a ccy supervisor armed and live for this
project", rather than each carrying a divergent copy.

The supervisor status file is GLOBAL — one per project root, written once at
launch, carrying no session id and no explicit ``armed`` flag (see
``read_supervisor_status``). So ``armed_supervisor_live`` answers a
PROJECT-scoped question, and "armed" is answered from ``ccy.env`` config rather
than from the status file (Plan 00283 Technical Decision 3): config-armed AND a
live process AND the recorded source fingerprint current.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

_CCY_DIR_PARTS: Final[tuple[str, str]] = (".claude", "ccy")
_CCY_ENV_NAME: Final[str] = "ccy.env"
_SUPERVISOR_SCRIPT_NAME: Final[str] = "claude-supervise.py"
# The shell launcher ccy.env's wrapper points at (see install/ccy_supervisor.py).
# It is a prefix of the script name, so one substring test recognises a wrapper
# that names either the launcher or the bare script (a pre-launcher install).
_SUPERVISOR_LAUNCHER_NAME: Final[str] = "claude-supervise"
_WRAPPER_EXPORT_KEY: Final[str] = "CCY_CLAUDE_WRAPPER"
_COMMENT_PREFIX: Final[str] = "#"

_SUPERVISE_SUBDIR: Final[str] = "supervise"
_SUPERVISOR_STATUS_FILENAME: Final[str] = "supervisor-status.json"
# Length of the sha256 hex prefix used as the source fingerprint. MUST match the
# supervisor's compute_source_hash (claude-supervise.py) or every launch reads
# as stale. Cross-process contract; the algorithm is trivial and stable.
_SOURCE_HASH_HEX_LEN: Final[int] = 12

_STATUS_KEY_PID: Final[str] = "pid"
_STATUS_KEY_SOURCE_HASH: Final[str] = "source_hash"

# The supervisor's INVARIANT provenance prefix on every line it types -- matches
# both the goal-injection form (`🤖 [ccy-supervisor] ...`) and the timestamped
# form (`🤖 [ccy-supervisor 2026-08-28 10:51:04] continue`). It deliberately has
# NO closing bracket, mirroring the supervisor's own `_BOT_PREFIX` in
# `.claude/ccy/claude-supervise.py`; a literal `🤖 [ccy-supervisor]` would miss
# every timestamped line.
CCY_SUPERVISOR_MARKER: Final[str] = "🤖 [ccy-supervisor"


def ccy_dir(project_root: Path) -> Path:
    """Resolve the ``.claude/ccy`` directory under ``project_root``."""
    return project_root.joinpath(*_CCY_DIR_PARTS)


def _active_wrapper_lines(ccy_env: Path) -> list[str]:
    """Non-comment lines of ``ccy.env`` that export the wrapper and name the supervisor."""
    if not ccy_env.is_file():
        return []
    try:
        content = ccy_env.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable {ccy_env} yields no active wrapper lines ([]), so the supervisor is treated as not configured",
            level=logging.DEBUG,
        )
        return []
    lines: list[str] = []
    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_COMMENT_PREFIX):
            continue
        if _WRAPPER_EXPORT_KEY in stripped and _SUPERVISOR_LAUNCHER_NAME in stripped:
            lines.append(stripped)
    return lines


def is_armed(ccy_env: Path) -> bool:
    """Armed = a non-comment line exports the wrapper referencing the supervisor."""
    return bool(_active_wrapper_lines(ccy_env))


#: The launcher is a POSIX shell script; this runs it without needing an exec bit.
SHELL_INTERPRETER: Final[str] = "sh"

#: What may follow the supervisor's file name: the end of its path token. Without
#: it ``claude-supervise-wrapper`` or ``claude-supervise_helper.py`` would count.
SUPERVISOR_NAME_END: Final[str] = r"(?=[\s\"'};]|$)"
# What may precede a file name standing alone: not the inside of a longer name.
_NAME_START: Final[str] = r"(?<![\w.\-])"


def file_name_token(file_name: str) -> re.Pattern[str]:
    """Pattern for ``file_name`` as a whole file name, not part of a longer one."""
    return re.compile(rf"{_NAME_START}{re.escape(file_name)}{SUPERVISOR_NAME_END}")


_SCRIPT_TOKEN_RE: Final[re.Pattern[str]] = file_name_token(_SUPERVISOR_SCRIPT_NAME)
_LAUNCHER_TOKEN_RE: Final[re.Pattern[str]] = file_name_token(_SUPERVISOR_LAUNCHER_NAME)

#: Spellings that put the wrapper in the deployed ``.claude/ccy/`` directory: the
#: installer's own self-locating armed line, and a path through ``.claude/ccy``.
DEPLOYED_LOCATIONS: Final[tuple[str, ...]] = (
    '$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/',
    ".claude/ccy/",
)


def names_deployed_file(line: str, deployed_ccy_dir: Path, file_name: str) -> bool:
    """Does ``line`` name ``file_name`` in the directory the launcher is deployed to?"""
    locations = (*DEPLOYED_LOCATIONS, f"{deployed_ccy_dir}/")
    return any(
        re.search(rf"{re.escape(location + file_name)}{SUPERVISOR_NAME_END}", line)
        for location in locations
    )


def wrapper_execs_bare_script(ccy_env: Path) -> bool:
    """True when an active wrapper line still execs ``claude-supervise.py`` directly.

    Such an install bypasses the version-gating launcher, so an unsupported
    system Python crashes the supervisor and Claude Code cannot start. A daemon
    upgrade repoints the line at the launcher.
    """
    return any(_SCRIPT_TOKEN_RE.search(line) for line in _active_wrapper_lines(ccy_env))


# A command word may start only where a shell word starts in a wrapper value:
# the start of the line, after whitespace, a quote or ``=``, or after the ``:-``
# of ``${CCY_CLAUDE_WRAPPER:-...}``. So ``foo-python3`` is not ``python3``.
_WORD_START: Final[str] = r"(?:^|(?<=[\s\"'=])|(?<=:-))"
# A Python interpreter word: ``python``, ``python3``, ``python3.N`` or a path to
# one, optionally behind ``env``. The ``word`` group is the interpreter itself
# (``env`` excluded).
_INTERPRETER_PATH_PREFIX: Final[str] = r"(?:[\w.+/$~{}][\w.+\-/$~{}]*)?/"
_INTERPRETER_PATTERN: Final[str] = (
    rf"(?:(?:{_INTERPRETER_PATH_PREFIX})?env\s+)?"
    rf"(?P<word>(?:{_INTERPRETER_PATH_PREFIX})?python(?:3(?:\.\d+)?)?)(?![\w.])"
    # Interpreter options (``-u``, ``-X dev``, ``-m mod``) between the word and
    # the path: the launcher cannot pass them on, so no ``sh`` rewrite keeps them.
    r"(?P<flags>(?:\s+-[^\s\"'}]+(?:\s+[^\s\"'}\-][^\s\"'}]*)?)*)"
)
# A shell variable used as the command word (``$PY``, ``${PY}``): what it runs
# cannot be known without the environment it is expanded in.
_VARIABLE_PATTERN: Final[str] = r"(?P<variable>\$\{?[A-Za-z_]\w*\}?)"
# What a path token may be made of before the supervisor's file name: an optional
# opening quote, then plain characters or ccy.env's self-locating
# ``$(cd ... && pwd)/`` spelling.
_WRAPPER_PATH_PREFIX: Final[str] = r"[\"']?(?:[^\s\"']*|\$\(cd\b.*?\bpwd\)/)"
#: Interpreter words whose dropping loses no choice of Python. The launcher's
#: search ends at ``python3``; it never tries ``python``, but wherever both exist
#: and ``python`` could run the supervisor, ``python3`` is a Python 3 too.
PLAIN_INTERPRETER_WORDS: Final[frozenset[str]] = frozenset({"python", "python3"})


def prefix_before_supervisor(file_name_pattern: str) -> re.Pattern[str]:
    """Pattern for a command word directly before the supervisor path.

    The word is a Python interpreter (group ``word``, with any interpreter
    options in group ``flags``, empty when there are none) or a shell variable
    (group ``variable``). Group ``gap`` is the whitespace before the path; the
    path itself is a lookahead, so a substitution touches nothing else.
    ``file_name_pattern`` is a regex for the supervisor file name the path must
    end in; the end of the path token is required after it.
    """
    return re.compile(
        rf"{_WORD_START}(?:{_INTERPRETER_PATTERN}|{_VARIABLE_PATTERN})(?P<gap>\s+)"
        rf"(?={_WRAPPER_PATH_PREFIX}{file_name_pattern}{SUPERVISOR_NAME_END})"
    )


_LAUNCHER_PREFIX_RE: Final[re.Pattern[str]] = prefix_before_supervisor(
    re.escape(_SUPERVISOR_LAUNCHER_NAME)
)


@dataclass(frozen=True)
class LauncherPrefix:
    """A command word in front of the launcher in an active wrapper line."""

    #: The interpreter word or the variable, as written.
    word: str
    #: True for a Python interpreter; False for a variable that cannot be checked.
    is_python: bool
    #: True when a daemon upgrade rewrites the line to ``sh``: a Python word with
    #: no options, before the launcher in the deployed directory.
    upgrade_repairs: bool


def wrapper_prefix_before_launcher(ccy_env: Path) -> LauncherPrefix | None:
    """The command word in front of the launcher in an active wrapper line, if any.

    The launcher is a ``sh`` script, so a Python interpreter in front of it runs
    shell text as Python and every ccy launch dies with a SyntaxError. Returns
    the first such word (a Python interpreter, or a variable that may hold one),
    or ``None`` when there is none.
    """
    for line in _active_wrapper_lines(ccy_env):
        match = _LAUNCHER_PREFIX_RE.search(line)
        if match is None:
            continue
        word = match.group("word")
        if word is None:
            return LauncherPrefix(match.group("variable"), is_python=False, upgrade_repairs=False)
        repairs = not match.group("flags") and names_deployed_file(
            line, ccy_env.parent, _SUPERVISOR_LAUNCHER_NAME
        )
        return LauncherPrefix(word, is_python=True, upgrade_repairs=repairs)
    return None


def wrapper_names_launcher(ccy_env: Path) -> bool:
    """True when an active wrapper line names the launcher (not just the bare script)."""
    return any(_LAUNCHER_TOKEN_RE.search(line) for line in _active_wrapper_lines(ccy_env))


def supervisor_relevance(context: RelevanceContext) -> Relevance:
    """Relevance verdict shared by every handler that only serves the supervisor.

    Plan 00330: ``goal_injection``, ``compaction_signal``,
    ``model_fallback_detector`` and ``tool_disable_advisor`` are actuated by
    the ccy PTY supervisor, so the config-optimisation review recommends
    them only where one is ARMED (``ccy.env`` exports the wrapper). One
    predicate here rather than four copies that could disagree.
    """
    return Relevance.when(
        is_armed(ccy_dir(context.project_root) / _CCY_ENV_NAME),
        present="the ccy supervisor is armed in .claude/ccy/ccy.env",
        absent="no armed ccy supervisor (.claude/ccy/ccy.env does not export the wrapper)",
    )


def daemon_untracked_dir(project_root: Path) -> Path:
    """Resolve the daemon untracked dir (install-mode-aware) from the root.

    The mode rule is ``install_layout`` -- the one definition -- not a copy of
    it, and no ``ProjectContext`` is needed (callers may pass a fallback cwd).
    """
    return get_untracked_dir(project_root)


def hash_supervisor_source(path: Path) -> str:
    """Short sha256 fingerprint of ``path`` — MUST match the supervisor's."""
    digest = hashlib.sha256(path.read_bytes(), usedforsecurity=False)
    return digest.hexdigest()[:_SOURCE_HASH_HEX_LEN]


def pid_alive(pid: object) -> bool:
    """Return True iff ``pid`` is a live process we can see.

    ``os.kill(pid, 0)`` raises ESRCH when the process is gone and EPERM when it
    exists but is owned by another user (still alive). Non-int / invalid pids
    are treated as not-alive.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError) as exc:
        # OverflowError: the status file is external JSON, so a corrupt or
        # oversized pid must be treated as not-alive, never crash the caller.
        log_and_continue(
            logger,
            exc,
            reason=f"a liveness probe that fails for pid {pid} treats it as not alive (False), so a corrupt pid never reads as a live supervisor",
            level=logging.DEBUG,
        )
        return False
    return True


def read_supervisor_status(project_root: Path) -> dict[str, Any]:
    """Read the running supervisor's status file.

    Returns an EMPTY dict when the file is absent or unreadable/invalid — a
    typed default the caller treats as "no supervisor advertised" (an empty dict
    is falsy), rather than conflating absence with an error via None.
    """
    status_path = (
        daemon_untracked_dir(project_root) / _SUPERVISE_SUBDIR / _SUPERVISOR_STATUS_FILENAME
    )
    if not status_path.is_file():
        return {}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable or invalid status file {status_path} reads as an empty status ({{}}), so the supervisor is treated as not reporting",
            level=logging.DEBUG,
        )
        return {}
    return data if isinstance(data, dict) else {}


def armed_supervisor_live(project_root: Path) -> bool:
    """True when a ccy supervisor is config-armed AND live AND source-current.

    All three must hold (Plan 00283 Technical Decision 3): "armed" from
    ``ccy.env``, "live" from the recorded pid being a running process, and
    "current" from the recorded source fingerprint matching the on-disk script.
    Answers a PROJECT-scoped question — the status file is global, so this
    cannot distinguish "this session's supervisor" from another session's in a
    shared checkout; the residual edge is documented in the plan.
    """
    supervisor_dir = ccy_dir(project_root)
    if not is_armed(supervisor_dir / _CCY_ENV_NAME):
        return False
    script = supervisor_dir / _SUPERVISOR_SCRIPT_NAME
    if not script.is_file():
        return False
    status = read_supervisor_status(project_root)
    if not status:
        return False
    if not pid_alive(status.get(_STATUS_KEY_PID)):
        return False
    running_hash = status.get(_STATUS_KEY_SOURCE_HASH)
    if not isinstance(running_hash, str) or not running_hash:
        return False
    try:
        ondisk_hash = hash_supervisor_source(script)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"a supervisor source {script} that cannot be hashed cannot be shown to match the armed one, so it is reported as not live (False)",
            level=logging.DEBUG,
        )
        return False
    return running_hash == ondisk_hash
