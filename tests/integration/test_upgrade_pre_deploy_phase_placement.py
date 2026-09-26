"""Where Layer 2 runs its pre-deploy phase (Plan 00376 Tasks 1.1, 1.2 and 3.1).

The cheap, always-run half of ``test_upgrade_pre_deploy_phase_runs_on_layer1``
(which drives a real upgrade and is marked slow). Both routes into
``upgrade_version.sh`` must:

- call ``run_pre_deploy_phase`` -- the gate -- once the target is checked out
  and BEFORE ``ensure_venv`` rebuilds the venv for it, so that a stop leaves
  nothing to undo but the checkout;
- call the report-only config compatibility check once the target's venv is
  verified and before the first deploy.

The gate reads ``--skip-reading-confirmation=<digest>`` from the arguments, or
from ``UPGRADE_FLAGS`` when a genuine Layer 1 handed over, and never asks
whether a terminal is attached; its stop codes in bash are the ones the Python
gate returns; and no environment variable switches it off.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.install.upgrade_gate import SKIP_READING_FLAG, GateVerdict

_LAYER2: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "upgrade_version.sh"
# GATE_SAFE_PATH, _gate_dir_is_trusted() and _gate_trusted_path() moved here
# (Plan 00376 review2 MAJOR 1): _sanitise_layer2_env() needs the trusted path
# to reset PATH at Layer 2 entry, before any other library -- including this
# one -- is sourced.
_ENV_SANITISE: Final[Path] = (
    Path(__file__).resolve().parents[2] / "scripts" / "install" / "env_sanitise.sh"
)
_GATE: Final[str] = "run_pre_deploy_phase"
_COMPAT: Final[str] = "run_config_compatibility_check"
_FAST_PATH_START: Final[str] = "Running idempotent deployment steps"
_ENSURE_VENV: Final[str] = "VENV_PATH=$(ensure_venv "
_VERIFY_VENV: Final[str] = 'verify_venv "$VENV_PYTHON"'
_FIRST_DEPLOY: Final[str] = 'deploy_all_hooks "$PROJECT_ROOT"'
_STEP_6: Final[str] = 'log_step "6"'
_STEP_8: Final[str] = 'log_step "8"'


def _script() -> str:
    return _LAYER2.read_text(encoding="utf-8") + "\n" + _ENV_SANITISE.read_text(encoding="utf-8")


def _call(text: str, name: str, start: int) -> int:
    match = re.compile(rf"^\s*{name}\s*$", re.MULTILINE).search(text, start)
    assert match is not None, f"{name} is not called after offset {start}"
    return match.start()


def _function_body(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    # The closing brace may be indented (Plan 00376 review2 MAJOR 1 moved
    # some functions into a guarded `if ...; then ... fi` block in
    # env_sanitise.sh, following the same indentation output.sh already
    # uses), so this tolerates leading whitespace rather than assuming the
    # unindented top-level style every OTHER function in upgrade_version.sh
    # still uses.
    match = re.compile(r"\n[ \t]*\}\n").search(text, start)
    assert match is not None, f"no closing brace found for {name}"
    return text[start : match.start()]


def test_the_idempotent_path_gates_before_the_venv_and_checks_compat_before_deploying() -> None:
    text = _script()
    fast_path = text.index(_FAST_PATH_START)
    gate = _call(text, _GATE, fast_path)
    compat = _call(text, _COMPAT, fast_path)
    assert gate < text.index(_ENSURE_VENV, fast_path)
    assert text.index(_VERIFY_VENV, fast_path) < compat < text.index(_FIRST_DEPLOY, fast_path)


def test_the_direct_path_gates_after_checkout_and_before_the_venv() -> None:
    text = _script()
    step_6 = text.index(_STEP_6)
    gate = _call(text, _GATE, step_6)
    compat = _call(text, _COMPAT, step_6)
    assert gate < text.index(_ENSURE_VENV, step_6)
    assert text.index(_VERIFY_VENV, step_6) < compat < text.index(_STEP_8)


def test_nothing_checks_compatibility_against_the_pre_checkout_tree() -> None:
    text = _script()
    body = _function_body(text, _COMPAT)
    assert "CompatibilityChecker" in body
    assert "CompatibilityChecker" not in text.replace(body, "")


def test_the_gate_honours_the_flag_and_never_infers_from_a_terminal() -> None:
    text = _script()
    assert SKIP_READING_FLAG in text
    assert "UPGRADE_FLAGS" in text
    body = _function_body(text, _GATE)
    assert "upgrade_gate_standalone.py" in body
    assert "-t 0" not in text, "a TTY test would disarm the gate for every agent"


def test_the_bash_stop_codes_are_the_gates_own() -> None:
    text = _script()
    for name, verdict in (
        ("GATE_NEEDS_ACKNOWLEDGEMENT", GateVerdict.NEEDS_ACKNOWLEDGEMENT),
        ("GATE_NEEDS_APPROVAL", GateVerdict.NEEDS_APPROVAL),
    ):
        assert re.search(rf"^{name}={verdict.exit_code}$", text, re.MULTILINE), name


def test_a_stop_restores_the_installed_version_not_a_handed_over_ref() -> None:
    """Review MAJOR 1/2: the restore target is what is installed, on every route."""
    text = _script()
    body = _function_body(text, "abort_before_deploy")
    assert "_restore_target" in body
    assert "reset --hard" in body
    restore = _function_body(text, "_restore_target")
    assert "INSTALLED_VERSION" in restore
    assert "_installed_release_from_docs" in restore
    assert "HOOKS_DAEMON_UPGRADE_PREVIOUS_REF" not in text


def test_the_gate_reads_the_installed_version_not_the_checkouts() -> None:
    body = _function_body(_script(), _GATE)
    assert '--installed-stamp "$INSTALLED_VERSION"' in body
    assert '--target-stamp "$INSTALL_STAMP"' in body
    assert "--from" not in body


def test_no_environment_variable_switches_the_gate_off() -> None:
    """Review MAJOR 4: the exported phase-done sentinel turned the whole gate off."""
    text = _script()
    assert "HOOKS_DAEMON_PRE_DEPLOY_PHASE_DONE" not in text
    body = _function_body(text, _GATE)
    assert not re.search(r"^\s*if \[ -n \"\$\{HOOKS_DAEMON_\w+", body, re.MULTILINE), body


def test_no_environment_override_picks_the_gate_interpreter() -> None:
    """Review of e27bd73f: HOOKS_DAEMON_PYTHON ran a crafted interpreter as the gate."""
    text = _script()
    body = _function_body(text, _GATE)
    assert "HOOKS_DAEMON_PYTHON" not in body
    assert '"$GATE_PYTHON" -I -S ' in body, "no PYTHON* variable, site-packages or .pth code"
    picker = _function_body(text, "_pick_gate_python")
    assert "unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH" in picker
    assert "venv" not in picker.split("{", 1)[1], "the project's venv is agent-writable"


def test_the_installed_version_ignores_the_venv_overrides() -> None:
    """HOOKS_DAEMON_VENV_PATH to a forged venv made the gate see the target installed."""
    text = _script()
    body = _function_body(text, "_read_installed_version")
    assert "(unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH; resolve_existing_venv_python" in body
    assert "/untracked/venv-*)" in body, "only this daemon dir's own venvs count"
    assert 'INSTALLED_VERSION="$(get_venv_version "$venv_dir")"' in body
    assert re.search(r"^_read_installed_version$", text, re.MULTILINE)


def test_everything_that_feeds_the_gate_runs_on_the_fixed_system_path() -> None:
    """Fresh review BLOCKER 1b: a tool planted on PATH answered for the gate.

    review2 MAJOR 2: a GATE_SAFE_PATH LOCATION is not necessarily trusted
    CONTENT (Homebrew's default layout is user-owned), so every function that
    feeds the gate resolves its tools from the ownership-and-permission
    filtered `_gate_trusted_path`, never the raw `$GATE_SAFE_PATH` list.
    """
    text = _script()
    for name in (
        _GATE,
        "_pick_gate_python",
        "_read_installed_version",
        "_installed_release_from_docs",
        "_target_release",
        "_restore_target",
        "abort_before_deploy",
    ):
        assert 'PATH="$(_gate_trusted_path)"' in _function_body(text, name), name
    assert re.search(r'^\s*GATE_SAFE_PATH="/usr/bin:/bin:', text, re.MULTILINE)


def test_gate_tool_resolves_only_trusted_locations() -> None:
    body = _function_body(_script(), "_gate_tool")
    assert '"$(_gate_trusted_path)"' in body
    assert "GATE_SAFE_PATH" not in body, "must go through the trust filter, not the raw list"


def test_only_a_root_owned_unwritable_directory_is_trusted() -> None:
    """review2 MAJOR 2: an ownership/permission check, not just a fixed list."""
    body = _function_body(_script(), "_gate_dir_is_trusted")
    assert "stat -c '%u'" in body or "stat -f '%u'" in body, "owner uid is read"
    assert '[ "$owner" = "0" ]' in body, "only root-owned directories are trusted"
    assert "8#022" in body, "group- and world-write bits (022) are rejected"


# A `stat` that answers from the directory's NAME (`<owner>-<mode>`), so the
# ownership half is decided the same way under any uid (review4 m3: a real
# root-owned directory exists only when the suite runs as root). STAT_STYLE
# picks which spelling it understands: GNU `-c` or BSD `-f`, the fallback
# `_gate_dir_is_trusted` takes when `-c` fails. Parameter expansion only: its
# PATH is the directory holding it.
_FAKE_STAT = """\
#!/bin/sh
flag="$1"; format="$2"; dir="$3"
case "$flag" in
    -c) [ "$STAT_STYLE" = gnu ] || exit 1 ;;
    -f) [ "$STAT_STYLE" = bsd ] || exit 1 ;;
    *) exit 1 ;;
esac
name="${dir##*/}"
owner="${name%%-*}"
case "$format" in
    %u) if [ "$owner" = root ]; then echo 0; else echo 1000; fi ;;
    %a | %Lp) echo "${name#*-}" ;;
    *) exit 1 ;;
esac
"""


@pytest.mark.parametrize("style", ["gnu", "bsd"])
@pytest.mark.parametrize(
    ("name", "trusted"),
    [
        ("root-755", True),
        ("root-555", True),
        ("user-755", False),
        ("root-777", False),
        ("root-775", False),
        ("root-757", False),
        ("root-7x5", False),
    ],
)
def test_gate_dir_is_trusted_decides_by_owner_and_write_bits(
    tmp_path: Path, style: str, name: str, trusted: bool
) -> None:
    """Real execution of the pure ownership/permission check, isolated from
    the rest of Layer 2 (no real upgrade, no network, no venv build), with
    `stat` stubbed so neither the uid running the suite nor chmod decides."""
    # _function_body() stops just before the closing brace (it is meant for
    # substring assertions, not re-execution), so it is added back here.
    function = f"{_function_body(_script(), '_gate_dir_is_trusted')}\n}}"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "stat").write_text(_FAKE_STAT)
    (fake_bin / "stat").chmod(0o755)
    harness = tmp_path / "harness.sh"
    harness.write_text(
        f'#!/bin/bash\nset -uo pipefail\nGATE_SAFE_PATH="{fake_bin}"\n{function}\n"$@"\n'
    )
    directory = tmp_path / name
    directory.mkdir()

    result = subprocess.run(
        ["bash", str(harness), "_gate_dir_is_trusted", str(directory)],
        env={**os.environ, "STAT_STYLE": style},
        check=False,
    )

    assert (result.returncode == 0) is trusted, (name, style)


def test_gate_dir_is_trusted_rejects_what_it_cannot_stat(tmp_path: Path) -> None:
    """No `stat` answering either spelling is not trust."""
    function = f"{_function_body(_script(), '_gate_dir_is_trusted')}\n}}"
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    harness = tmp_path / "harness.sh"
    harness.write_text(
        f'#!/bin/bash\nset -uo pipefail\nGATE_SAFE_PATH="{empty_bin}"\n{function}\n"$@"\n'
    )
    directory = tmp_path / "root-755"
    directory.mkdir()

    result = subprocess.run(
        ["bash", str(harness), "_gate_dir_is_trusted", str(directory)], check=False
    )

    assert result.returncode != 0


def test_imported_shell_functions_are_dropped_before_anything_runs() -> None:
    """An exported `timeout()` function shadowed the tool by name."""
    for script in (_LAYER2, _LAYER2.with_name("upgrade.sh")):
        text = script.read_text(encoding="utf-8")
        prelude = text.index("set -euo pipefail")
        drop = text.index('unset -f "$_imported_function"')
        assert prelude < drop < text.index("\n}\n"), script.name


def test_the_gate_runs_in_a_cleared_environment_and_a_zero_exit_needs_its_verdict() -> None:
    body = _function_body(_script(), _GATE)
    assert '("$env_bin" -i "PATH=$GATE_SAFE_PATH"' in body
    assert '"$timeout_bin" "$GATE_TIMEOUT_SECONDS"' in body
    assert '--verdict-file "$verdict_file" --nonce "$nonce"' in body
    assert "/dev/urandom" in body
    assert '[ "$nonce_line" != "nonce=$nonce" ]' in body
    assert '[ ! -L "$verdict_file" ] && [ -O "$verdict_file" ]' in body


def test_the_verdict_dir_ignores_an_inherited_tmpdir() -> None:
    """review2 MINOR 1: a bare `mktemp -d` honours inherited TMPDIR, and the
    upgrade guard denies TMPDIR only on the SAME command as the upgrade."""
    body = _function_body(_script(), _GATE)
    assert 'mktemp -d -p /tmp' in body


def test_the_used_approval_is_removed_only_on_success_on_both_paths() -> None:
    text = _script()
    calls = [m.start() for m in re.finditer(r"^\s*consume_used_approval\s*$", text, re.MULTILINE)]
    assert len(calls) == 2, calls
    fast_path_exit = text.index("exit 0\nfi", text.index(_FAST_PATH_START))
    assert calls[0] < fast_path_exit
    assert calls[1] > text.index('log_step "17"')


def test_the_layer1_handoff_is_a_file_bound_to_the_parent_process() -> None:
    body = _function_body(_script(), "_read_handoff")
    assert '"$PPID"' in body
    assert "-O" in body
    assert 'rm -f -- "$path"' in body
