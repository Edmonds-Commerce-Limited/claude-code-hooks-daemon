"""Plan 00487 Task 1.2 -- the supervisor plugin loader.

A plugin is named explicitly with a repeatable ``--plugin <name>=<worker.py>``
flag before ``--``; nothing is found by scanning. Every refusal skips that one
plugin and the session still starts. The host vets each file WITHOUT importing
it (the host never imports a worker half); the ``--worker`` subprocess imports
what the host passed on, so the disabled set rides on ``--disable-plugin`` and
survives every worker hot reload.
"""

from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import (
    GOOD_BODY,
    PLUGIN_DIR_MODE,
    make_runtime,
    plugin_source,
    spec,
    write_plugin,
)

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_OWN_UIDS = frozenset({os.getuid(), 0})
# A uid set that matches neither the file's owner nor root, so a file this test
# process wrote is "owned by somebody else".
_FOREIGN_UIDS = frozenset({2**31 - 2})


# -- flags -------------------------------------------------------------------


class TestFlags:
    def test_plugin_flag_is_repeatable_and_keeps_order(self) -> None:
        flags = _mod._parse_supervisor_flags(
            ["--plugin", "a=/p/a.py", "--arm", "--plugin", "b=/p/b.py", "--", "claude"]
        )
        assert flags.plugin == ["a=/p/a.py", "b=/p/b.py"]

    def test_plugin_flag_defaults_to_empty(self) -> None:
        assert _mod._parse_supervisor_flags(["--", "claude"]).plugin == []

    def test_disable_plugin_flag_is_repeatable(self) -> None:
        flags = _mod._parse_supervisor_flags(
            ["--disable-plugin", "a", "--disable-plugin", "b", "--", "claude"]
        )
        assert flags.disable_plugin == ["a", "b"]

    def test_child_argv_is_never_parsed_for_plugin_flags(self) -> None:
        flags = _mod._parse_supervisor_flags(["--", "claude", "--plugin", "x=/y"])
        assert flags.plugin == []

    def test_usage_names_the_plugin_flag(self) -> None:
        assert "--plugin" in _mod._USAGE

    def test_worker_flags_carry_plugins_and_the_disabled_set(self) -> None:
        specs, disabled = _mod._parse_worker_plugin_flags(
            ["--worker", "--arm", "--plugin", "a=/p/a.py", "--disable-plugin", "b"]
        )
        assert specs == ["a=/p/a.py"]
        assert disabled == frozenset({"b"})

    def test_worker_flags_default_to_nothing(self) -> None:
        assert _mod._parse_worker_plugin_flags(["--worker"]) == ([], frozenset())


# -- name and spec validation ------------------------------------------------


class TestSpecParsing:
    def test_a_well_formed_spec_splits_at_the_first_equals(self, tmp_path: Path) -> None:
        parsed = _mod.parse_plugin_spec(f"max-age={tmp_path}/max=age.py")
        assert parsed.name == "max-age"
        assert str(parsed.path) == f"{tmp_path}/max=age.py"

    @pytest.mark.parametrize(
        "raw",
        [
            "no-equals-sign",
            "=/abs/p.py",
            "Upper=/abs/p.py",
            "1lead=/abs/p.py",
            "has space=/abs/p.py",
            "slash/name=/abs/p.py",
            f"{'a' * 33}=/abs/p.py",
            "ok=",
        ],
    )
    def test_malformed_specs_are_refused_with_a_closed_reason(self, raw: str) -> None:
        with pytest.raises(_mod.PluginLoadError) as caught:
            _mod.parse_plugin_spec(raw)
        assert caught.value.reason in _mod._PLUGIN_LOAD_REASONS

    def test_a_relative_path_is_refused(self) -> None:
        with pytest.raises(_mod.PluginLoadError) as caught:
            _mod.parse_plugin_spec("ok=relative/p.py")
        assert caught.value.reason == _mod._LOAD_REASON_NOT_ABSOLUTE

    def test_the_longest_legal_name_is_accepted(self) -> None:
        assert _mod.parse_plugin_spec(f"{'a' * 32}=/abs/p.py").name == "a" * 32


# -- file vetting ------------------------------------------------------------


class TestFileChecks:
    def test_a_regular_owned_private_file_passes(self, tmp_path: Path) -> None:
        path = write_plugin(tmp_path, "p")
        assert _mod.check_plugin_file(path, allowed_uids=_OWN_UIDS) is None

    def test_a_missing_file_is_not_a_file(self, tmp_path: Path) -> None:
        assert (
            _mod.check_plugin_file(tmp_path / "nope.py", allowed_uids=_OWN_UIDS)
            == _mod._LOAD_REASON_NOT_A_FILE
        )

    def test_a_directory_is_not_a_file(self, tmp_path: Path) -> None:
        assert _mod.check_plugin_file(tmp_path, allowed_uids=_OWN_UIDS) == (
            _mod._LOAD_REASON_NOT_A_FILE
        )

    def test_a_symlink_is_not_a_regular_file(self, tmp_path: Path) -> None:
        real = write_plugin(tmp_path / "real", "p")
        link = tmp_path / "link.py"
        link.symlink_to(real)
        assert _mod.check_plugin_file(link, allowed_uids=_OWN_UIDS) == (
            _mod._LOAD_REASON_NOT_A_FILE
        )

    @pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
    def test_a_group_or_world_writable_file_is_refused(self, tmp_path: Path, mode: int) -> None:
        path = write_plugin(tmp_path, "p")
        path.chmod(mode)
        assert _mod.check_plugin_file(path, allowed_uids=_OWN_UIDS) == (_mod._LOAD_REASON_WRITABLE)

    @pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
    def test_a_group_or_world_writable_directory_is_refused(
        self, tmp_path: Path, mode: int
    ) -> None:
        path = write_plugin(tmp_path / "d", "p")
        path.parent.chmod(mode)
        try:
            assert _mod.check_plugin_file(path, allowed_uids=_OWN_UIDS) == (
                _mod._LOAD_REASON_WRITABLE
            )
        finally:
            path.parent.chmod(PLUGIN_DIR_MODE)

    def test_a_file_owned_by_someone_else_is_refused(self, tmp_path: Path) -> None:
        path = write_plugin(tmp_path, "p")
        assert _mod.check_plugin_file(path, allowed_uids=_FOREIGN_UIDS) == (_mod._LOAD_REASON_OWNER)

    def test_the_default_allowed_owners_are_this_uid_and_root(self) -> None:
        assert _mod._default_plugin_uids() == frozenset({os.getuid(), 0})


# -- the host registry (no imports) -----------------------------------------


def _host(specs: list[str], written: list[list[dict[str, str]]] | None = None) -> Any:
    sink = written if written is not None else []
    return _mod.PluginHost(
        specs,
        write_status=lambda entries: sink.append(entries),
        allowed_uids=_OWN_UIDS,
    )


class TestPluginHost:
    def test_good_specs_are_loaded_in_flag_order(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        b = write_plugin(tmp_path, "b")
        host = _host([spec("a", a), spec("b", b)])
        assert [(e["name"], e["state"]) for e in host.status_entries()] == [
            ("a", _mod._PLUGIN_STATE_LOADED),
            ("b", _mod._PLUGIN_STATE_LOADED),
        ]

    def test_a_bad_file_is_skipped_and_the_rest_still_load(self, tmp_path: Path) -> None:
        good = write_plugin(tmp_path, "good")
        bad = write_plugin(tmp_path, "bad")
        bad.chmod(0o666)
        host = _host([spec("bad", bad), spec("good", good)])
        by_name = {e["name"]: e for e in host.status_entries()}
        assert by_name["bad"]["state"] == _mod._PLUGIN_STATE_FAILED
        assert by_name["bad"]["reason"] == f"load: {_mod._LOAD_REASON_WRITABLE}"
        assert by_name["good"]["state"] == _mod._PLUGIN_STATE_LOADED

    def test_a_malformed_spec_is_listed_as_failed_under_a_placeholder_name(self) -> None:
        host = _host(["not-a-spec"])
        [entry] = host.status_entries()
        assert entry["state"] == _mod._PLUGIN_STATE_FAILED
        assert entry["reason"] == f"load: {_mod._LOAD_REASON_BAD_SPEC}"

    def test_a_duplicate_name_is_refused(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        host = _host([spec("a", a), spec("a", a)])
        states = [e["state"] for e in host.status_entries()]
        assert states == [_mod._PLUGIN_STATE_LOADED, _mod._PLUGIN_STATE_FAILED]
        assert host.status_entries()[1]["reason"] == f"load: {_mod._LOAD_REASON_DUPLICATE}"

    def test_load_refusals_become_startup_failures_naming_a_validated_name(
        self, tmp_path: Path
    ) -> None:
        bad = write_plugin(tmp_path, "bad")
        bad.chmod(0o666)
        host = _host([spec("bad", bad), "Bad Spec"])
        failures = host.take_startup_failures()
        # A malformed spec has no trustworthy name, so it yields no notice (the
        # fixed template needs a validated name); the status entry still shows it.
        assert [(f.plugin, f.kind, f.hook) for f in failures] == [
            ("bad", _mod._PLUGIN_KIND_LOAD, _mod._PLUGIN_HOOK_LOAD)
        ]
        assert host.take_startup_failures() == []

    def test_worker_argv_passes_only_loadable_plugins_in_order(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        bad = write_plugin(tmp_path, "bad")
        bad.chmod(0o666)
        b = write_plugin(tmp_path, "b")
        host = _host([spec("a", a), spec("bad", bad), spec("b", b)])
        assert host.worker_argv() == ["--plugin", spec("a", a), "--plugin", spec("b", b)]

    def test_record_failure_disables_once_and_survives_in_worker_argv(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        host = _host([spec("a", a)])
        assert host.record_failure("a", _mod._PLUGIN_KIND_EXCEPTION, _mod._PLUGIN_HOOK_ON_IDLE)
        assert not host.record_failure("a", _mod._PLUGIN_KIND_OVERRUN, _mod._PLUGIN_HOOK_ON_IDLE)
        assert host.worker_argv() == ["--plugin", spec("a", a), "--disable-plugin", "a"]
        [entry] = host.status_entries()
        assert entry["state"] == _mod._PLUGIN_STATE_DISABLED
        assert entry["reason"] == "exception in on_idle"

    def test_a_load_failure_reported_by_the_worker_is_failed_not_disabled(
        self, tmp_path: Path
    ) -> None:
        a = write_plugin(tmp_path, "a")
        host = _host([spec("a", a)])
        host.record_failure("a", _mod._PLUGIN_KIND_LOAD, _mod._PLUGIN_HOOK_LOAD)
        assert host.status_entries()[0]["state"] == _mod._PLUGIN_STATE_FAILED

    def test_an_unknown_plugin_failure_is_ignored(self) -> None:
        host = _host([])
        assert not host.record_failure("ghost", _mod._PLUGIN_KIND_EXCEPTION, "on_idle")

    def test_a_worker_confirmation_records_the_version(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        host = _host([spec("a", a)])
        host.record_loaded("a", "9.9.9")
        assert host.status_entries()[0]["version"] == "9.9.9"

    def test_status_is_rewritten_on_every_change(self, tmp_path: Path) -> None:
        a = write_plugin(tmp_path, "a")
        written: list[list[dict[str, str]]] = []
        host = _host([spec("a", a)], written)
        host.record_loaded("a", "1.0")
        host.record_failure("a", _mod._PLUGIN_KIND_OVERRUN, _mod._PLUGIN_HOOK_ON_IDLE)
        assert len(written) == 3
        assert written[-1][0]["state"] == _mod._PLUGIN_STATE_DISABLED

    def test_a_plugin_named_by_disable_plugin_starts_disabled_and_stays_off(
        self, tmp_path: Path
    ) -> None:
        a = write_plugin(tmp_path, "a")
        b = write_plugin(tmp_path, "b")
        host = _mod.PluginHost(
            [spec("a", a), spec("b", b)],
            write_status=lambda entries: None,
            allowed_uids=_OWN_UIDS,
            disabled=["a", "ghost"],
        )
        by_name = {e["name"]: e for e in host.status_entries()}
        assert by_name["a"]["state"] == _mod._PLUGIN_STATE_DISABLED
        assert by_name["a"]["reason"] == _mod._DISABLED_BY_FLAG_REASON
        assert by_name["b"]["state"] == _mod._PLUGIN_STATE_LOADED
        assert host.worker_argv() == [
            "--plugin",
            spec("a", a),
            "--plugin",
            spec("b", b),
            "--disable-plugin",
            "a",
        ]

    def test_no_specs_means_no_plugin_key_is_ever_written(self) -> None:
        written: list[list[dict[str, str]]] = []
        _host([], written)
        assert written == []

    def test_the_in_process_runtime_is_built_lazily_from_loadable_plugins(
        self, tmp_path: Path
    ) -> None:
        a = write_plugin(tmp_path, "a")
        host = _mod.PluginHost(
            [spec("a", a)],
            write_status=lambda entries: None,
            allowed_uids=_OWN_UIDS,
            state_root=tmp_path / "state",
            status_dir=tmp_path / "untracked",
            marker_path=tmp_path / "marker.json",
        )
        runtime = host.in_process_runtime()
        assert [name for name, _version in runtime.loaded] == ["a"]
        assert host.in_process_runtime() is runtime


# -- supervisor-status.json --------------------------------------------------


class TestSupervisorStatusFile:
    def test_plugins_are_listed_with_name_version_state_reason(self, tmp_path: Path) -> None:
        plugins = [{"name": "a", "version": "1.0", "state": "loaded", "reason": ""}]
        path = _mod.write_supervisor_status(
            tmp_path, version="3.68.0", source_hash="h", pid=1, started_at=0.0, plugins=plugins
        )
        assert path is not None
        assert json.loads(path.read_text())["plugins"] == plugins

    def test_the_key_is_absent_when_no_plugins_were_given(self, tmp_path: Path) -> None:
        path = _mod.write_supervisor_status(
            tmp_path, version="3.68.0", source_hash="h", pid=1, started_at=0.0
        )
        assert path is not None
        assert "plugins" not in json.loads(path.read_text())


# -- the worker argv carries the plugins and the disabled set ----------------


class _FakeStream:
    def close(self) -> None:
        return None


class _FakePopen:
    launched: ClassVar[list[list[str]]] = []

    def __init__(self, argv: list[str], **_kwargs: object) -> None:
        self.argv = argv
        self.stdin = _FakeStream()
        self.stdout = _FakeStream()
        _FakePopen.launched.append(argv)

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


class TestPolicyWorkerArgv:
    @pytest.fixture(autouse=True)
    def _fake_popen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakePopen.launched = []
        monkeypatch.setattr(_mod.subprocess, "Popen", _FakePopen)

    def test_start_appends_the_extra_argv(self, tmp_path: Path) -> None:
        worker = _mod.PolicyWorker(
            tmp_path / "s.py", dry_run=True, extra_argv=lambda: ["--plugin", "a=/p"]
        )
        assert worker.start()
        assert _FakePopen.launched[0][-2:] == ["--plugin", "a=/p"]

    def test_every_restart_re_reads_the_extra_argv_so_the_disabled_set_survives(
        self, tmp_path: Path
    ) -> None:
        extra: list[str] = ["--plugin", "a=/p"]
        worker = _mod.PolicyWorker(tmp_path / "s.py", dry_run=True, extra_argv=lambda: list(extra))
        worker.start()
        extra.extend(["--disable-plugin", "a"])
        worker.restart()
        assert _FakePopen.launched[-1][-2:] == ["--disable-plugin", "a"]

    def test_no_extra_argv_changes_nothing(self, tmp_path: Path) -> None:
        worker = _mod.PolicyWorker(tmp_path / "s.py", dry_run=True)
        worker.start()
        assert _FakePopen.launched[0] == [
            _mod.sys.executable,
            str(tmp_path / "s.py"),
            "--worker",
        ]


# -- the worker half of the loader ------------------------------------------


def _bare_runtime(tmp_path: Path) -> Any:
    return _mod.PluginRuntime(
        state_root=tmp_path / "state",
        status_dir=tmp_path / "untracked",
        marker_path=tmp_path / "untracked" / "marker.json",
        session_ids=frozenset,
        allowed_uids=_OWN_UIDS,
    )


def _failures(runtime: Any) -> list[tuple[str, str, str]]:
    return [(f.plugin, f.kind, f.hook) for f in runtime.failures]


_LOAD_FAILURE = [("p", "load", "load")]


class TestRuntimeLoad:
    def test_a_good_plugin_loads_and_reports_its_version(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"good": GOOD_BODY})
        assert runtime.loaded == [("good", "1.2.3")]

    def test_the_factory_gets_an_api_with_a_private_state_dir(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"good": GOOD_BODY})
        api = runtime.half("good").api
        assert api.api_version == _mod._PLUGIN_API_VERSION
        assert api.state_dir == tmp_path / "state" / "good"
        assert stat.S_IMODE(api.state_dir.stat().st_mode) == 0o700

    def test_plugins_load_in_flag_order(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"zeta": GOOD_BODY, "alpha": GOOD_BODY})
        assert [name for name, _ in runtime.loaded] == ["zeta", "alpha"]

    @pytest.mark.parametrize("api", [2, 0, "1", None, True, 1.0])
    def test_a_plugin_api_major_mismatch_is_a_load_failure(
        self, tmp_path: Path, api: object
    ) -> None:
        path = write_plugin(tmp_path / "plugins", "p", source=plugin_source("p", api=api))
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset())
        assert runtime.loaded == []
        assert _failures(runtime) == _LOAD_FAILURE

    def test_a_missing_plugin_api_is_a_load_failure(self, tmp_path: Path) -> None:
        source = plugin_source("p").replace("PLUGIN_API = 1\n", "")
        path = write_plugin(tmp_path / "plugins", "p", source=source)
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset())
        assert _failures(runtime) == _LOAD_FAILURE

    @pytest.mark.parametrize(
        "source",
        [
            "PLUGIN_API = 1\nraise RuntimeError('import time')\n",
            "PLUGIN_API = 1\ndef broken(:\n",
            "PLUGIN_API = 1\n",
            "PLUGIN_API = 1\ndef create_worker_half(api):\n    raise ValueError('boom')\n",
            "PLUGIN_API = 1\ndef create_worker_half(api):\n    return object()\n",
        ],
    )
    def test_import_errors_and_a_bad_factory_are_load_failures(
        self, tmp_path: Path, source: str
    ) -> None:
        path = write_plugin(tmp_path / "plugins", "p", source=source)
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset())
        assert runtime.loaded == []
        assert _failures(runtime) == _LOAD_FAILURE

    def test_a_half_whose_name_differs_from_the_flag_is_refused(self, tmp_path: Path) -> None:
        path = write_plugin(tmp_path / "plugins", "p", source=plugin_source("other"))
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset())
        assert runtime.loaded == []
        assert _failures(runtime) == _LOAD_FAILURE

    def test_one_bad_plugin_does_not_stop_the_next(self, tmp_path: Path) -> None:
        bad = write_plugin(tmp_path / "plugins", "bad", source="PLUGIN_API = 9\n")
        good = write_plugin(tmp_path / "plugins", "good")
        runtime = _bare_runtime(tmp_path)
        runtime.load([("bad", bad), ("good", good)], frozenset())
        assert [name for name, _ in runtime.loaded] == ["good"]

    def test_the_worker_re_vets_the_file_before_importing_it(self, tmp_path: Path) -> None:
        marker = tmp_path / "imported"
        source = f"open({str(marker)!r}, 'w').close()\n" + plugin_source("p")
        path = write_plugin(tmp_path / "plugins", "p", source=source)
        path.chmod(0o666)
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset())
        assert not marker.exists()
        assert _failures(runtime) == _LOAD_FAILURE

    def test_a_disabled_plugin_is_never_imported(self, tmp_path: Path) -> None:
        marker = tmp_path / "imported"
        source = f"open({str(marker)!r}, 'w').close()\n" + plugin_source("p")
        path = write_plugin(tmp_path / "plugins", "p", source=source)
        runtime = _bare_runtime(tmp_path)
        runtime.load([("p", path)], frozenset({"p"}))
        assert not marker.exists()
        assert runtime.loaded == []
        assert _failures(runtime) == []


# -- main(): a refused plugin never stops the session ------------------------


class TestMainStartsWithRefusedPlugins:
    def test_a_missing_plugin_file_still_runs_the_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv(_mod._NO_WORKER_ENV, "1")
        stdin = (tmp_path / "stdin").open("w+")
        monkeypatch.setattr(_mod.sys, "stdin", stdin)
        code = _mod.main(
            [
                "--plugin",
                f"ghost={tmp_path}/ghost.py",
                "--plugin",
                "garbled",
                "--log",
                str(tmp_path / "decision.log"),
                "--",
                "bash",
                "-lc",
                "exit 5",
            ]
        )
        stdin.close()
        assert code == 5
        assert "ghost" in (tmp_path / "decision.log").read_text()
