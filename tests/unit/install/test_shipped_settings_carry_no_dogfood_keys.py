"""No install or upgrade route ships this repository's own Claude Code choices.

Plan 00468 Task 1.2 (plugin audit P1). In self-install mode the tracked
``.claude/settings.json`` is BOTH this repository's live settings AND the
template every client receives: the shell installers name it as
``SETTINGS_JSON_SOURCE``, a fresh install copies it whole, and an upgrade's
three-way merge delivers any top-level key that is new in it. So a key added
for dogfooding reaches every client on the next release. That is how the
Defence Before Fix plugin's ``enabledPlugins`` and ``extraKnownMarketplaces``
very nearly shipped, and how ``plansDirectory`` did ship.

Each of these keys belongs in the tracked ``.claude/settings.local.json``,
which Claude Code merges over ``settings.json`` for this checkout and which no
installer copies. This test runs every route a template reaches a client by —
the shell copy, the three-way merge and the Python generator — and fails when
any of them would deliver one.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - runs bash on this repo's own shell library
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.settings_merge import merge_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / ".claude" / "settings.json"
DEPLOY_LIB = REPO_ROOT / "scripts" / "install" / "settings_deploy.sh"

#: Keys that describe THIS checkout's Claude Code set-up, never a client's:
#: which plugins it runs, which marketplaces it trusts, and where its own plan
#: mode writes (a client's plan workflow is opt-in and its directory is
#: configurable, so no single value is right for every client).
DOGFOOD_ONLY_KEYS = ("enabledPlugins", "extraKnownMarketplaces", "plansDirectory")

_SHELL_INSTALLERS = ("install_version.sh", "upgrade_version.sh")
_SOURCE_ASSIGNMENT = re.compile(r'^SETTINGS_JSON_SOURCE="\$DAEMON_DIR/(?P<path>[^"]+)"$', re.M)


def _template() -> dict[str, Any]:
    loaded = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("script", _SHELL_INSTALLERS)
def test_the_shell_installers_ship_the_file_this_test_checks(script: str) -> None:
    """If a script ever ships a different file, the checks below would pass on
    the wrong one; pin the source so that change fails here first."""
    text = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
    sources = _SOURCE_ASSIGNMENT.findall(text)
    assert sources == [".claude/settings.json"], sources


@pytest.mark.parametrize("key", DOGFOOD_ONLY_KEYS)
def test_the_template_itself_carries_no_dogfood_key(key: str) -> None:
    assert key not in _template(), (
        f"{key} is in {TEMPLATE.relative_to(REPO_ROOT)}, which ships to every client. "
        "Move it to .claude/settings.local.json."
    )


@pytest.mark.parametrize("key", DOGFOOD_ONLY_KEYS)
def test_a_fresh_shell_install_copies_no_dogfood_key(tmp_path: Path, key: str) -> None:
    """The fresh-install branch of ``deploy_settings_json`` copies the file whole."""
    target = tmp_path / "client" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    script = textwrap.dedent(f"""
        set -u
        print_success() {{ :; }}
        print_warning() {{ :; }}
        print_error()   {{ echo "ERROR: $*"; }}
        print_verbose() {{ :; }}
        OUTPUT_SH_LOADED=1
        source "{DEPLOY_LIB}"
        deploy_settings_json "{TEMPLATE}" "{target}" "" "" ""
    """)
    result = subprocess.run(  # nosec B603 B607 - bash, list form, no shell
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.VALIDATION_CHECK,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert key not in json.loads(target.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", DOGFOOD_ONLY_KEYS)
def test_an_upgrade_merge_delivers_no_dogfood_key(key: str) -> None:
    """Worst case for the merge: the previous template had none of today's
    top-level keys, so every one of them counts as new and is delivered."""
    merged, report = merge_settings(client={}, new_default=_template(), old_default={})
    assert key not in report.keys_delivered
    assert key not in merged


@pytest.mark.parametrize("key", DOGFOOD_ONLY_KEYS)
def test_the_python_installer_generates_no_dogfood_key(tmp_path: Path, key: str) -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from install import create_settings_json

    (tmp_path / ".claude").mkdir()
    create_settings_json(tmp_path)
    written = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert key not in written
