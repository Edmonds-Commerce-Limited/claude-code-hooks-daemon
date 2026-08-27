"""Tests for the generic agent-asset install subsystem (Plan 00279).

TDD RED phase for ``install/agent_assets.py``: the registry of daemon-shipped
agents, the version/md5 ledger, the classification helper
(absent | current | outdated | customised), the deploy/remove engine, and the
config-driven sync entry point.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.install import agent_assets
from claude_code_hooks_daemon.install.agent_assets import (
    AGENT_VERSION_MARKER_PREFIX,
    AGENTS_DIR_PARTS,
    DEDUPE_AGENT_NAME,
    OPUS_SECURITY_AGENT_NAME,
    SHIPPED_AGENTS,
    AgentAction,
    AgentAssetSpec,
    AgentAssetState,
    classify_agent,
    content_md5,
    deploy_agent,
    deploy_agents_if_enabled,
    deployed_agent_path,
    ledger,
    remove_agent,
    spec_by_name,
    spec_source_path,
    sync_agents,
)

#: Content md5 of the first shipped opus-security revision. Pinned here so the
#: ledger entry that keeps such a deployment upgradeable cannot be dropped.
_OPUS_SECURITY_V1_MD5 = "9724c2afde95dd7f33a2e53a40849c1b"


def _spec(name: str) -> AgentAssetSpec:
    return spec_by_name(name)


def _enabled_config(**kwargs: object) -> Config:
    """Config with plan_workflow + opus-security agent enabled."""
    return Config.model_validate(
        {
            "plan_workflow": {"enabled": True},
            "agents": {"opus_security": {"enabled": True}},
        }
    )


class TestRegistry:
    def test_registry_contains_both_first_payloads(self) -> None:
        names = {spec.name for spec in SHIPPED_AGENTS}
        assert DEDUPE_AGENT_NAME in names
        assert OPUS_SECURITY_AGENT_NAME in names

    def test_every_agent_name_is_namespaced(self) -> None:
        for spec in SHIPPED_AGENTS:
            assert spec.name.startswith("hooks-daemon-")

    def test_every_source_file_exists(self) -> None:
        for spec in SHIPPED_AGENTS:
            assert spec_source_path(spec).is_file()

    def test_spec_by_name_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            spec_by_name("no-such-agent")

    def test_every_source_carries_its_version_marker(self) -> None:
        for spec in SHIPPED_AGENTS:
            text = spec_source_path(spec).read_text()
            assert f"{AGENT_VERSION_MARKER_PREFIX} {spec.version} -->" in text

    def test_dedupe_agent_gated_on_plan_workflow(self) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        assert spec.gating_config_key == "plan_workflow.enabled"
        assert spec.is_enabled(Config.model_validate({"plan_workflow": {"enabled": True}}))
        assert not spec.is_enabled(Config())

    def test_opus_security_disabled_by_default(self) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        assert spec.gating_config_key == "agents.opus_security.enabled"
        assert not spec.is_enabled(Config())
        assert spec.is_enabled(_enabled_config())


class TestLedger:
    def test_ledger_maps_agent_to_version_to_md5(self) -> None:
        book = ledger()
        for spec in SHIPPED_AGENTS:
            assert spec.name in book
            assert spec.version in book[spec.name]

    def test_current_ledger_entry_matches_bundled_file(self) -> None:
        """DBF guard: editing a bundled agent without bumping its version and
        re-recording its md5 must fail loudly here, never ship silently."""
        book = ledger()
        for spec in SHIPPED_AGENTS:
            assert book[spec.name][spec.version] == content_md5(
                spec_source_path(spec).read_text()
            ), f"{spec.name}: bundled content does not match the ledger md5 for v{spec.version}"

    def test_dedupe_agent_carries_historic_versions(self) -> None:
        """Every previously shipped dedupe-scout revision must be in the
        ledger, or existing pristine installs would be classified customised
        and never upgraded again."""
        spec = _spec(DEDUPE_AGENT_NAME)
        assert len(spec.historic_md5s) >= 5

    def test_opus_security_agent_ledgers_its_first_shipped_revision(self) -> None:
        """The v1.0.0 content md5 must stay in the ledger after the v1.1.0
        rewrite, so an already-deployed pristine copy classifies OUTDATED
        (upgradeable) rather than CUSTOMISED (frozen forever)."""
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        assert spec.version == "1.1.0"
        assert _OPUS_SECURITY_V1_MD5 in spec.historic_md5s


class TestClassification:
    def test_absent(self, tmp_path: Path) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        assert classify_agent(spec, tmp_path) is AgentAssetState.ABSENT

    def test_current(self, tmp_path: Path) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text(spec_source_path(spec).read_text())
        assert classify_agent(spec, tmp_path) is AgentAssetState.CURRENT

    def test_outdated(self, tmp_path: Path) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        historic = spec.historic_versions[0]
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        # Synthesise a file whose md5 equals a historic entry is impossible;
        # instead classification must key on the md5 SET, so patch a spec with
        # a known historic md5 for a controlled body.
        body = "old shipped content\n"
        patched = AgentAssetSpec(
            name=spec.name,
            version=spec.version,
            gating_config_key=spec.gating_config_key,
            is_enabled=spec.is_enabled,
            historic_versions=(("legacy-1", content_md5(body)),),
        )
        target.write_text(body)
        assert classify_agent(patched, tmp_path) is AgentAssetState.OUTDATED
        assert historic  # historic entries exist on the real spec too

    def test_customised(self, tmp_path: Path) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text("my own hacked-up agent\n")
        assert classify_agent(spec, tmp_path) is AgentAssetState.CUSTOMISED


class TestDeployAndRemove:
    def test_deploy_absent_writes_current_content(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        result = deploy_agent(spec, tmp_path)
        assert result.action is AgentAction.DEPLOYED
        assert classify_agent(spec, tmp_path) is AgentAssetState.CURRENT

    def test_deploy_current_is_kept(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        deploy_agent(spec, tmp_path)
        result = deploy_agent(spec, tmp_path)
        assert result.action is AgentAction.KEPT_CURRENT

    def test_deploy_outdated_overwrites(self, tmp_path: Path) -> None:
        body = "old shipped content\n"
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        patched = AgentAssetSpec(
            name=spec.name,
            version=spec.version,
            gating_config_key=spec.gating_config_key,
            is_enabled=spec.is_enabled,
            historic_versions=(("legacy-1", content_md5(body)),),
        )
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text(body)
        result = deploy_agent(patched, tmp_path)
        assert result.action is AgentAction.UPDATED
        assert classify_agent(spec, tmp_path) is AgentAssetState.CURRENT

    def test_deploy_never_clobbers_customised(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        custom_body = "my own hacked-up agent\n"
        target.write_text(custom_body)
        result = deploy_agent(spec, tmp_path)
        assert result.action is AgentAction.CUSTOMISED_WARNING
        assert target.read_text() == custom_body
        assert spec.name in result.message
        assert "customis" in result.message.lower()
        assert "discouraged" in result.message.lower()

    def test_remove_pristine(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        deploy_agent(spec, tmp_path)
        result = remove_agent(spec, tmp_path)
        assert result.action is AgentAction.REMOVED
        assert classify_agent(spec, tmp_path) is AgentAssetState.ABSENT

    def test_remove_refuses_customised(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text("my own hacked-up agent\n")
        result = remove_agent(spec, tmp_path)
        assert result.action is AgentAction.REFUSED_CUSTOMISED
        assert target.exists()

    def test_remove_absent_is_noop(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        result = remove_agent(spec, tmp_path)
        assert result.action is AgentAction.ALREADY_ABSENT


class TestSync:
    def test_sync_deploys_enabled_missing_agents(self, tmp_path: Path) -> None:
        report = sync_agents(tmp_path, _enabled_config())
        for spec in SHIPPED_AGENTS:
            assert deployed_agent_path(spec, tmp_path).is_file()
        actions = {r.name: r.action for r in report.results}
        assert actions[OPUS_SECURITY_AGENT_NAME] is AgentAction.DEPLOYED

    def test_sync_skips_disabled_absent_agents(self, tmp_path: Path) -> None:
        report = sync_agents(tmp_path, Config())
        for spec in SHIPPED_AGENTS:
            assert not deployed_agent_path(spec, tmp_path).exists()
        actions = {r.name: r.action for r in report.results}
        assert all(a is AgentAction.SKIPPED_DISABLED for a in actions.values())

    def test_sync_disabled_present_advises_removal_never_deletes(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        deploy_agent(spec, tmp_path)
        report = sync_agents(tmp_path, Config())
        assert deployed_agent_path(spec, tmp_path).is_file()
        result = next(r for r in report.results if r.name == spec.name)
        assert result.action is AgentAction.REMOVAL_ADVISED
        assert f"agents remove {spec.name}" in result.message

    def test_sync_warns_on_customised_enabled(self, tmp_path: Path) -> None:
        spec = _spec(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text("my own hacked-up agent\n")
        report = sync_agents(tmp_path, _enabled_config())
        result = next(r for r in report.results if r.name == spec.name)
        assert result.action is AgentAction.CUSTOMISED_WARNING
        assert target.read_text() == "my own hacked-up agent\n"

    def test_deploy_agents_if_enabled_loads_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        (config_dir / "hooks-daemon.yaml").write_text(
            "agents:\n  opus_security:\n    enabled: true\n"
        )
        report = deploy_agents_if_enabled(tmp_path, config_dir / "hooks-daemon.yaml")
        assert deployed_agent_path(_spec(OPUS_SECURITY_AGENT_NAME), tmp_path).is_file()
        assert report.results

    def test_deploy_agents_if_enabled_missing_config_is_noop_deploy(self, tmp_path: Path) -> None:
        report = deploy_agents_if_enabled(tmp_path, tmp_path / ".claude" / "hooks-daemon.yaml")
        actions = {r.name: r.action for r in report.results}
        assert all(a is AgentAction.SKIPPED_DISABLED for a in actions.values())


class TestDeployedLocation:
    def test_agents_dir_parts_is_claude_agents(self) -> None:
        assert AGENTS_DIR_PARTS == (".claude", "agents")

    def test_deployed_path_shape(self, tmp_path: Path) -> None:
        spec = _spec(DEDUPE_AGENT_NAME)
        assert deployed_agent_path(spec, tmp_path) == (
            tmp_path / ".claude" / "agents" / f"{spec.name}.md"
        )


class TestOpusSecurityContent:
    def test_generalised_no_estate_specifics(self) -> None:
        text = spec_source_path(_spec(OPUS_SECURITY_AGENT_NAME)).read_text()
        for banned in ("fable-safeguard-delegation", "shellscripts/", "nftables", "Fable 5"):
            assert banned not in text

    def test_contract_markers_present(self) -> None:
        text = spec_source_path(_spec(OPUS_SECURITY_AGENT_NAME)).read_text()
        assert "-opus-security-SUMMARY" in text
        assert "-opus-security-DETAIL" in text
        assert "model: opus" in text

    def test_ownership_marker_present(self) -> None:
        marker = "DAEMON-OWNED FILE - do not edit"
        for spec in SHIPPED_AGENTS:
            assert marker in spec_source_path(spec).read_text()


def test_module_has_no_mutable_registry() -> None:
    assert isinstance(agent_assets.SHIPPED_AGENTS, tuple)
