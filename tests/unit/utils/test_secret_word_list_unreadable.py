"""N231: a secret word list that EXISTS but cannot be read is an error, never "no terms".

An ABSENT list stays inert (the documented opt-in). A list the project did
create but the daemon cannot read must not silently become an empty term set:
that would let ``sensitive_content`` allow every write, the QA sweeps report
clean and every redaction sink redact nothing, all without checking one term.

Root can read any chmod-000 file, so unreadability is simulated by patching
``Path.read_text`` or by putting a directory where the list should be.
"""

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import front_controller
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon import server
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TERM = "zzqx-nonsense-term"
_LIST_NAME = "terms.lst"
_WRITE_INPUT: dict[str, Any] = {
    "tool_name": "Write",
    "tool_input": {"file_path": "/tmp/f.txt", "content": "innocuous"},
}


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


def _unreadable_list(tmp_path: Path) -> Path:
    """A word list that exists but cannot be read: a directory in its place."""
    path = tmp_path / _LIST_NAME
    path.mkdir()
    return path


def _handler_for(path: Path) -> SensitiveContentHandler:
    handler = SensitiveContentHandler()
    handler._secret_word_list_path = path.name
    handler._project_root_override = path.parent
    return handler


def _config_naming_the_list(tmp_path: Path) -> Path:
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text(
        "handlers:\n  pre_tool_use:\n    sensitive_content:\n"
        f"      options:\n        secret_word_list_path: {_LIST_NAME}\n"
    )
    return config


def _load_script(name: str) -> ModuleType:
    script = _REPO_ROOT / "scripts" / "qa" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_n231", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestLoadSecretTerms:
    def test_absent_list_is_still_inert(self, tmp_path: Path) -> None:
        assert sr.load_secret_terms(tmp_path / "absent.lst") == ()

    def test_directory_in_the_lists_place_raises(self, tmp_path: Path) -> None:
        with pytest.raises(sr.SecretWordListUnreadableError):
            sr.load_secret_terms(_unreadable_list(tmp_path))

    def test_read_oserror_raises(self, tmp_path: Path) -> None:
        path = tmp_path / _LIST_NAME
        path.write_text(f"{_TERM}\n")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(sr.SecretWordListUnreadableError):
                sr.load_secret_terms(path)

    def test_dangling_symlink_raises(self, tmp_path: Path) -> None:
        path = tmp_path / _LIST_NAME
        path.symlink_to(tmp_path / "nowhere")
        with pytest.raises(sr.SecretWordListUnreadableError):
            sr.load_secret_terms(path)

    def test_error_is_an_oserror_so_oserror_sinks_withhold(self) -> None:
        assert issubclass(sr.SecretWordListUnreadableError, OSError)

    def test_message_names_the_path_and_never_the_content(self, tmp_path: Path) -> None:
        path = tmp_path / _LIST_NAME
        path.write_text(f"{_TERM}\n")
        with patch.object(Path, "read_text", side_effect=PermissionError(f"leaks {_TERM}")):
            with pytest.raises(sr.SecretWordListUnreadableError) as caught:
                sr.load_secret_terms(path)
        assert str(path) in str(caught.value)
        assert _TERM not in str(caught.value)


class TestCachedSecretTerms:
    def test_unreadable_list_is_not_cached_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / _LIST_NAME
        path.write_text(f"{_TERM}\n")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(sr.SecretWordListUnreadableError):
                sr.get_cached_secret_terms(path)
        # Readable again: the failure must not have been remembered as ().
        assert sr.get_cached_secret_terms(path) == (_TERM,)

    def test_directory_raises_every_time(self, tmp_path: Path) -> None:
        path = _unreadable_list(tmp_path)
        for _ in range(2):
            with pytest.raises(sr.SecretWordListUnreadableError):
                sr.get_cached_secret_terms(path)

    def test_absent_list_is_still_cached_inert(self, tmp_path: Path) -> None:
        assert sr.get_cached_secret_terms(tmp_path / "absent.lst") == ()


class TestActiveTerms:
    def test_configured_unreadable_list_raises(self, tmp_path: Path) -> None:
        path = _unreadable_list(tmp_path)
        with patch.object(sr, "_resolve_active_path", return_value=path):
            with pytest.raises(sr.SecretWordListUnreadableError):
                sr.get_active_secret_terms()


class TestSinkHelper:
    def test_withholds_when_the_list_is_unreadable(self) -> None:
        with patch.object(
            sr, "get_active_secret_terms", side_effect=sr.SecretWordListUnreadableError("x")
        ):
            assert sr.redact_structure_active({"a": "b"}) == sr.WITHHELD_PLACEHOLDER

    def test_redacts_when_terms_exist(self) -> None:
        with patch.object(sr, "get_active_secret_terms", return_value=(_TERM,)):
            assert sr.redact_structure_active({"a": f"x {_TERM}"}) == {"a": "x [REDACTED]"}

    def test_passes_through_when_inert(self) -> None:
        with patch.object(sr, "get_active_secret_terms", return_value=()):
            assert sr.redact_structure_active({"a": "b"}) == {"a": "b"}


class TestSensitiveContentHandler:
    def test_unreadable_list_denies_with_a_purpose_built_reason(self, tmp_path: Path) -> None:
        handler = _handler_for(_unreadable_list(tmp_path))
        assert handler.matches(_WRITE_INPUT) is True
        result = handler.handle(_WRITE_INPUT)
        assert result.decision == Decision.DENY
        assert "secret word list" in (result.reason or "")
        assert "cannot be read" in (result.reason or "")

    def test_reason_never_contains_a_term(self, tmp_path: Path) -> None:
        path = tmp_path / _LIST_NAME
        path.write_text(f"{_TERM}\n")
        handler = _handler_for(path)
        with patch.object(Path, "read_text", side_effect=PermissionError(f"leaks {_TERM}")):
            result = handler.handle(_WRITE_INPUT)
        assert result.decision == Decision.DENY
        assert _TERM not in (result.reason or "")

    def test_absent_list_still_allows(self, tmp_path: Path) -> None:
        handler = _handler_for(tmp_path / "absent.lst")
        assert handler.matches(_WRITE_INPUT) is False


class TestQaChecks:
    @pytest.mark.parametrize("script", ["check_sensitive_content", "check_git_history"])
    def test_unreadable_list_is_a_config_error(self, tmp_path: Path, script: str) -> None:
        module = _load_script(script)
        config = _config_naming_the_list(tmp_path)
        _unreadable_list(tmp_path)
        with pytest.raises(module.ConfigError, match="cannot be read"):
            module.resolve_secret_terms(config, tmp_path)

    @pytest.mark.parametrize("script", ["check_sensitive_content", "check_git_history"])
    def test_absent_list_is_still_inert(self, tmp_path: Path, script: str) -> None:
        module = _load_script(script)
        config = _config_naming_the_list(tmp_path)
        assert module.resolve_secret_terms(config, tmp_path) == ()


class TestRedactionSinks:
    def test_error_log_withholds_the_payload(self, tmp_path: Path) -> None:
        with patch.object(
            sr, "get_active_secret_terms", side_effect=sr.SecretWordListUnreadableError("x")
        ):
            front_controller.log_error_to_file(
                "PreToolUse",
                RuntimeError("boom"),
                {"tool_input": {"content": _TERM}},
                project_root=tmp_path,
            )
        logs = list(tmp_path.rglob("hook-errors.log"))
        assert logs, "the error itself must still be logged"
        text = logs[0].read_text()
        assert _TERM not in text
        assert sr.WITHHELD_PLACEHOLDER in text

    def test_blocking_response_log_is_withheld(self) -> None:
        with patch.object(
            server, "get_active_secret_terms", side_effect=sr.SecretWordListUnreadableError("x")
        ):
            logged = server.redacted_blocking_response(json.dumps({"r": _TERM}))
        assert logged == sr.WITHHELD_PLACEHOLDER


class TestModelFallbackSnapshot:
    def test_snapshot_is_withheld_when_the_list_is_unreadable(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.handlers.session_start import model_fallback_detector as mfd

        handler = mfd.ModelFallbackDetectorHandler()
        with (
            patch.object(
                mfd, "get_active_secret_terms", side_effect=sr.SecretWordListUnreadableError("x")
            ),
            patch.object(handler, "_resolve_snapshot_dir", return_value=tmp_path / "snaps"),
        ):
            notes = handler._write_snapshots([], "/t.jsonl")
        assert len(notes) == 1
        assert "withheld" in notes[0]
        assert not (tmp_path / "snaps").exists()


class TestCliDispatch:
    def test_main_stops_with_an_error_naming_the_path(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import argparse

        from claude_code_hooks_daemon.daemon import cli

        def raising(_args: argparse.Namespace) -> int:
            raise sr.SecretWordListUnreadableError("secret word list exists but cannot be read: /p")

        parser = argparse.ArgumentParser()
        with (
            patch.object(cli, "build_parser", return_value=parser),
            patch.object(parser, "parse_args", return_value=argparse.Namespace(func=raising)),
            patch.object(cli, "apply_global_project_root", side_effect=lambda a: a),
            patch.object(cli, "_reexec_daemon_launch_with_explicit_project_root"),
        ):
            assert cli.main() == 1
        assert "cannot be read" in capsys.readouterr().err
