"""Completeness gate for relay guard eligibility (Plan 00290 dogfood fix).

Two invariants, both proven fresh from real deployed sources rather than
just against the typed catalogue in isolation:

1. Every wired event's generated-forwarder guard presence matches its own
   ``EventIDMeta.relay_eligible`` — no event can get a guard the catalogue
   says it must not, and none can silently lose one it should have.
2. Every ``response_mode`` value the deployed ``.claude/init.sh`` template
   actually TRANSLATES client-side (``"status"``, ``"worktree"``) is used
   only by a ``bash_key`` the catalogue marks relay-ineligible — grepping
   the real template (not a hand-copied literal) keeps bash and Python in
   lockstep: if a future init.sh gains a new ``response_mode`` branch, this
   test fails until the matching event is marked ``raw_stdout`` (or
   ``requires_client_translation``) in the catalogue.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.events import EventIDMeta, wired_event_metas
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"

_SAMPLE_SOURCE_TEMPLATE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

send_request_stdin "{json_key}"
"""


class TestGuardPresenceMatchesMeta:
    @pytest.mark.parametrize("meta", wired_event_metas(), ids=lambda m: m.bash_key)
    def test_generated_guard_presence_matches_relay_eligible(self, meta: EventIDMeta) -> None:
        transport = TransportConfig(relay_enabled=True)
        source = _SAMPLE_SOURCE_TEMPLATE.format(json_key=meta.json_key)

        result = generate_forwarder_content(
            source, meta.bash_key, transport, Path("/proj/untracked")
        )

        has_guard = "relay hot path" in result
        assert has_guard == meta.relay_eligible, (
            f"{meta.bash_key}: guard presence ({has_guard}) does not match "
            f"relay_eligible ({meta.relay_eligible})"
        )

    @pytest.mark.parametrize(
        "hook_file",
        sorted(p.name for p in _HOOKS_DIR.iterdir() if p.is_file() and p.name != "README.md"),
    )
    def test_real_deployed_hook_guard_presence_matches_relay_eligible(self, hook_file: str) -> None:
        """Same assertion, but against the REAL shipped forwarder source —
        catches drift between the synthetic template above and reality."""
        by_bash_key = {meta.bash_key: meta for meta in wired_event_metas()}
        if hook_file not in by_bash_key:
            pytest.skip(f"{hook_file} is not a wired-event forwarder")
        meta = by_bash_key[hook_file]

        source = (_HOOKS_DIR / hook_file).read_text()
        transport = TransportConfig(relay_enabled=True)

        result = generate_forwarder_content(source, hook_file, transport, Path("/proj/untracked"))

        has_guard = "relay hot path" in result
        assert has_guard == meta.relay_eligible, (
            f"{hook_file}: guard presence ({has_guard}) does not match "
            f"relay_eligible ({meta.relay_eligible})"
        )


class TestResponseModeTranslatedEventsAreIneligible:
    def test_every_response_mode_branch_in_init_sh_is_relay_ineligible(self) -> None:
        """Grep the DEPLOYED init.sh template for every
        ``response_mode == '<mode>'`` branch (the client-side JSON-unwrap
        translations a byte-pump relay cannot perform), map each mode back to
        the real hook script(s) that pass it as the second
        ``send_request_stdin`` argument, and assert every one of those
        bash_keys is relay-ineligible in the catalogue."""
        init_sh_content = _INIT_SH.read_text()
        modes = set(re.findall(r"response_mode == '([a-z]+)'", init_sh_content))
        assert modes, "no response_mode branches found — grep pattern drifted from init.sh"
        assert modes == {"status", "worktree"}, (
            "init.sh gained/lost a response_mode branch; update the catalogue's "
            "raw_stdout/requires_client_translation flags to match, then this "
            f"assertion. Found: {modes}"
        )

        by_bash_key = {meta.bash_key: meta for meta in wired_event_metas()}
        mode_call_pattern = re.compile(r'send_request_stdin\s+"[^"]*"\s+"([a-z]*)"')

        translated_bash_keys: set[str] = set()
        for hook_file in _HOOKS_DIR.iterdir():
            if not hook_file.is_file() or hook_file.name not in by_bash_key:
                continue
            match = mode_call_pattern.search(hook_file.read_text())
            if match and match.group(1) in modes:
                translated_bash_keys.add(hook_file.name)

        assert translated_bash_keys == {"status-line", "worktree-create"}

        for bash_key in translated_bash_keys:
            meta = by_bash_key[bash_key]
            assert meta.relay_eligible is False, (
                f"{bash_key} passes a translated response_mode but the catalogue "
                "marks it relay-eligible"
            )
