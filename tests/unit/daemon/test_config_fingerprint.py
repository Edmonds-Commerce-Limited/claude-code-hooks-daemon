"""Tests for the config half of the daemon freshness verdict (Plan 00415).

A running daemon binds TWO things at startup: the handler code it imports and
the config it resolves. Plan 00371's fingerprint covers the code only, so a
config edit without a restart used to leave ``check-source-fresh`` and the
acceptance harness reporting FRESH over a daemon still graded against the old
config. These tests cover the config fingerprint and the single combined
verdict every consumer reads.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.source_fingerprint import (
    CONFIG_PARSE_FAILED_FINGERPRINT,
    HEALTH_KEY_CONFIG_FINGERPRINT,
    HEALTH_KEY_SOURCE_FINGERPRINT,
    DaemonFingerprints,
    compute_config_fingerprint,
    compute_current_project_fingerprints,
    compute_daemon_identity_fingerprint,
    describe_daemon_staleness,
)

_BASE_YAML = "version: '1.0'\ndaemon:\n  idle_timeout_seconds: 600\n"
_EDITED_YAML = "version: '1.0'\ndaemon:\n  idle_timeout_seconds: 900\n"
_COMMENTED_YAML = (
    "# a reformatted comment only\nversion: '1.0'\ndaemon:\n  idle_timeout_seconds: 600\n"
)

_SUBPROCESS_TIMEOUT_SECONDS = 120

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_config(project: Path, text: str) -> Path:
    claude_dir = project / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_dir / "hooks-daemon.yaml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def _health(fingerprints: DaemonFingerprints) -> dict[str, Any]:
    """A health payload shaped like the one ``DaemonController.get_health`` sends."""
    return {
        "status": "healthy",
        HEALTH_KEY_SOURCE_FINGERPRINT: fingerprints.source,
        HEALTH_KEY_CONFIG_FINGERPRINT: fingerprints.config,
    }


class TestComputeConfigFingerprint:
    """The resolved config model, hashed as canonical JSON."""

    def test_same_config_hashes_identically(self) -> None:
        config = Config.model_validate({"daemon": {"idle_timeout_seconds": 600}})
        again = Config.model_validate({"daemon": {"idle_timeout_seconds": 600}})

        assert compute_config_fingerprint(config) == compute_config_fingerprint(again)

    def test_a_changed_value_changes_the_digest(self) -> None:
        before = Config.model_validate({"daemon": {"idle_timeout_seconds": 600}})
        after = Config.model_validate({"daemon": {"idle_timeout_seconds": 900}})

        assert compute_config_fingerprint(before) != compute_config_fingerprint(after)

    def test_a_handler_option_change_changes_the_digest(self) -> None:
        """Plan 00413 N14's evidence: one handler option changed three probe outcomes."""
        before = Config.model_validate(
            {"handlers": {"pre_tool_use": {"ask_user_question_blocker": {"enabled": True}}}}
        )
        after = Config.model_validate(
            {
                "handlers": {
                    "pre_tool_use": {
                        "ask_user_question_blocker": {
                            "enabled": True,
                            "options": {"mode": "unattended"},
                        }
                    }
                }
            }
        )

        assert compute_config_fingerprint(before) != compute_config_fingerprint(after)

    def test_is_never_the_parse_failed_sentinel(self) -> None:
        assert compute_config_fingerprint(Config()) != CONFIG_PARSE_FAILED_FINGERPRINT

    def test_identical_across_separate_processes(self) -> None:
        """Determinism across processes, hash seeds and working directories.

        The daemon hashes its config after it has forked and chdir'd to ``/``;
        the checker hashes from wherever it was invoked. An unstable
        serialisation would make the guard cry stale at random, which is
        worse than the gap it closes.
        """
        script = (
            "import sys\n"
            "from claude_code_hooks_daemon.config.models import Config\n"
            "from claude_code_hooks_daemon.daemon.source_fingerprint import "
            "compute_config_fingerprint\n"
            "print(compute_config_fingerprint(Config.find_and_load(sys.argv[1])))\n"
        )
        digests = set()
        for seed, cwd in (("1", "/"), ("2", str(_REPO_ROOT)), ("3", "/tmp")):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            completed = subprocess.run(
                [sys.executable, "-c", script, str(_REPO_ROOT)],
                capture_output=True,
                text=True,
                cwd=cwd,
                env=env,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
                check=True,
            )
            digests.add(completed.stdout.strip())

        assert len(digests) == 1
        assert compute_config_fingerprint(Config.find_and_load(_REPO_ROOT)) in digests


class TestComputeCurrentProjectFingerprints:
    """Both halves, computed from what is on disk now."""

    def test_config_half_hashes_the_resolved_model(self, tmp_path: Path) -> None:
        _write_config(tmp_path, _BASE_YAML)

        result = compute_current_project_fingerprints(tmp_path)

        expected = compute_config_fingerprint(Config.find_and_load(tmp_path))
        assert result.config == expected
        assert result.source == compute_daemon_identity_fingerprint()

    def test_a_comment_only_edit_is_not_drift(self, tmp_path: Path) -> None:
        """Hashing the resolved model, not the bytes, so a comment is not a change."""
        _write_config(tmp_path, _BASE_YAML)
        before = compute_current_project_fingerprints(tmp_path)
        _write_config(tmp_path, _COMMENTED_YAML)

        assert compute_current_project_fingerprints(tmp_path) == before

    def test_a_value_edit_is_drift(self, tmp_path: Path) -> None:
        _write_config(tmp_path, _BASE_YAML)
        before = compute_current_project_fingerprints(tmp_path)
        _write_config(tmp_path, _EDITED_YAML)

        after = compute_current_project_fingerprints(tmp_path)

        assert after.config != before.config
        assert after.source == before.source

    def test_schema_invalid_config_hashes_to_the_sentinel(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "project_handlers:\n  enabled: not-a-boolean\n")

        result = compute_current_project_fingerprints(tmp_path)

        assert result.config == CONFIG_PARSE_FAILED_FINGERPRINT
        assert result.source == compute_daemon_identity_fingerprint()

    def test_yaml_syntax_error_is_a_verdict_not_a_crash(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "daemon: [unclosed\n")

        result = compute_current_project_fingerprints(tmp_path)

        assert result.config == CONFIG_PARSE_FAILED_FINGERPRINT

    def test_no_config_is_not_the_same_as_a_broken_config(self, tmp_path: Path) -> None:
        """The daemon runs on defaults with no config but refuses a broken one."""
        result = compute_current_project_fingerprints(tmp_path)

        assert result.config == compute_config_fingerprint(Config())
        assert result.config != CONFIG_PARSE_FAILED_FINGERPRINT


class TestDescribeDaemonStaleness:
    """The single combined verdict: every consumer reads this, never one half."""

    _CURRENT = DaemonFingerprints(source="s" * 64, config="c" * 64)

    def test_fresh_when_both_halves_match(self) -> None:
        assert describe_daemon_staleness(_health(self._CURRENT), self._CURRENT) is None

    def test_no_health_payload_is_a_staleness_risk(self) -> None:
        message = describe_daemon_staleness(None, self._CURRENT)

        assert message is not None
        assert "restart" in message.lower()

    def test_code_drift_names_the_code(self) -> None:
        running = DaemonFingerprints(source="o" * 64, config=self._CURRENT.config)

        message = describe_daemon_staleness(_health(running), self._CURRENT)

        assert message is not None
        assert "STALE" in message
        assert "code" in message
        assert "config" not in message.lower()

    def test_config_drift_is_stale_even_when_code_matches(self) -> None:
        """The defect Plan 00415 fixes: config moved, code did not, verdict said FRESH."""
        running = DaemonFingerprints(source=self._CURRENT.source, config="o" * 64)

        message = describe_daemon_staleness(_health(running), self._CURRENT)

        assert message is not None
        assert "STALE" in message
        assert "config" in message
        assert "loaded code" not in message

    def test_both_drifted_names_both(self) -> None:
        running = DaemonFingerprints(source="o" * 64, config="o" * 64)

        message = describe_daemon_staleness(_health(running), self._CURRENT)

        assert message is not None
        assert "code" in message
        assert "config" in message

    def test_missing_config_fingerprint_cannot_be_verified(self) -> None:
        """A daemon predating Plan 00415 reports code only; that is not FRESH."""
        payload = {HEALTH_KEY_SOURCE_FINGERPRINT: self._CURRENT.source}

        message = describe_daemon_staleness(payload, self._CURRENT)

        assert message is not None
        assert HEALTH_KEY_CONFIG_FINGERPRINT in message

    def test_missing_source_fingerprint_cannot_be_verified(self) -> None:
        payload = {HEALTH_KEY_CONFIG_FINGERPRINT: self._CURRENT.config}

        message = describe_daemon_staleness(payload, self._CURRENT)

        assert message is not None
        assert HEALTH_KEY_SOURCE_FINGERPRINT in message

    def test_unparseable_on_disk_config_says_so(self) -> None:
        current = DaemonFingerprints(
            source=self._CURRENT.source, config=CONFIG_PARSE_FAILED_FINGERPRINT
        )

        message = describe_daemon_staleness(_health(self._CURRENT), current)

        assert message is not None
        assert "does not parse" in message

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            {},
            {HEALTH_KEY_SOURCE_FINGERPRINT: None, HEALTH_KEY_CONFIG_FINGERPRINT: None},
            {HEALTH_KEY_SOURCE_FINGERPRINT: 7, HEALTH_KEY_CONFIG_FINGERPRINT: ["x"]},
        ],
    )
    def test_never_raises_and_never_trusts_a_malformed_payload(
        self, payload: dict[str, Any] | None
    ) -> None:
        assert describe_daemon_staleness(payload, self._CURRENT) is not None
