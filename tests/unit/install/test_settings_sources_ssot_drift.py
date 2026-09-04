"""SSoT drift guard: every settings.json hook source agrees with the catalogue.

Plan 00185 Phase 4. The session-start "Missing hook registration" flood was a
drift between the running daemon's expectation (``wired_event_metas()``) and the
registrations a project actually had. These tests fail loudly if ANY of the live
settings.json / forwarder sources drift from the single source of truth, so the
class of bug can never silently reappear:

- ``install.py::_DAEMON_FORWARDER_HOOKS`` (root installer generator/registrar)
- the tracked ``.claude/settings.json`` template (copied verbatim by the shell
  installers on install AND upgrade)
- ``scripts/install/hooks_deploy.sh::_DAEMON_HOOK_BASENAMES`` (forwarder files the
  installer deploys + owns)

The authoritative set is ``wired_event_metas()``; StatusLine registers under the
top-level ``statusLine`` key, not the ``hooks`` section, so it is excluded from
the two ``hooks``-block sources but INCLUDED in the deployed-forwarder basenames.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from claude_code_hooks_daemon.constants.events import STATUS_LINE_JSON_KEY, wired_event_metas
from claude_code_hooks_daemon.utils.hook_registration import (
    _BASH_KEYS_WITH_TIMEOUT,
    _DEFAULT_HOOK_TIMEOUT_SECONDS,
    HOOK_COMMAND_TEMPLATE,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _wired_json_keys_excluding_status_line() -> set[str]:
    return {m.json_key for m in wired_event_metas() if m.json_key != STATUS_LINE_JSON_KEY}


def _wired_bash_keys_all() -> set[str]:
    return {m.bash_key for m in wired_event_metas()}


def _load_install_module():
    """Import the root install.py by path (it is not a package module)."""
    install_path = _REPO_ROOT / "install.py"
    spec = importlib.util.spec_from_file_location("_install_for_drift_test", install_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_install_py_forwarder_hooks_match_catalogue() -> None:
    install = _load_install_module()
    json_keys = set(install._DAEMON_FORWARDER_HOOKS.values())
    assert json_keys == _wired_json_keys_excluding_status_line()


def test_tracked_settings_json_matches_catalogue() -> None:
    settings = json.loads((_REPO_ROOT / ".claude" / "settings.json").read_text())
    assert set(settings["hooks"].keys()) == _wired_json_keys_excluding_status_line()


def test_hooks_deploy_basenames_match_catalogue() -> None:
    text = (_REPO_ROOT / "scripts" / "install" / "hooks_deploy.sh").read_text()
    # Anchor the closing ``)`` to the start of a line — a comment inside the
    # array body (e.g. "(wired for coverage)") also contains a ``)``.
    match = re.search(r"_DAEMON_HOOK_BASENAMES=\((.*?)^\)", text, re.DOTALL | re.MULTILINE)
    assert match is not None, "could not locate _DAEMON_HOOK_BASENAMES array"
    # Strip comments, then collect the bare basename tokens.
    body_lines = [line.split("#", 1)[0] for line in match.group(1).splitlines()]
    basenames = {tok for line in body_lines for tok in line.split()}
    # The deployed forwarders are exactly the wired bash_keys (status-line
    # included — the script is deployed even though it registers elsewhere).
    assert basenames == _wired_bash_keys_all()


def test_install_py_timeout_set_matches_reconciler() -> None:
    # The set of forwarders that carry an explicit per-invocation timeout must be
    # identical in install.py and the reconciler, else a fresh install and the
    # session self-heal would disagree on which hooks get a timeout.
    install = _load_install_module()
    assert set(install._HOOKS_WITH_TIMEOUT) == set(_BASH_KEYS_WITH_TIMEOUT)


def test_install_py_timeout_value_matches_reconciler() -> None:
    # install.py hardcodes the timeout literal inline in create_all_hooks; guard
    # it against the reconciler's _DEFAULT_HOOK_TIMEOUT_SECONDS so the two never
    # silently drift to different values.
    text = (_REPO_ROOT / "install.py").read_text()
    match = re.search(r'command\["timeout"\]\s*=\s*(\d+)', text)
    assert match is not None, "could not locate the timeout assignment in install.py"
    assert int(match.group(1)) == _DEFAULT_HOOK_TIMEOUT_SECONDS


def test_install_py_command_template_matches_reconciler() -> None:
    # install.py's _hook_cmd f-string and the reconciler's HOOK_COMMAND_TEMPLATE
    # must render byte-identical commands, else fresh-install and self-heal would
    # register different command strings for the same event.
    text = (_REPO_ROOT / "install.py").read_text()
    match = re.search(r"return (f'[^']*/\.claude/hooks/\{bash_key\}')", text)
    assert match is not None, "could not locate the _hook_cmd template in install.py"
    # Normalise both to the same placeholder form for comparison.
    install_template = match.group(1)[2:-1]  # strip the f'...' wrapper
    assert install_template == HOOK_COMMAND_TEMPLATE
