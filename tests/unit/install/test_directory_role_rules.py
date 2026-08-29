"""Tests for the shipped ``.claude/rules/`` directory-role pointer files (Plan 00288, D5)."""

from pathlib import Path

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.install import directory_role_rules
from claude_code_hooks_daemon.install.directory_role_rules import (
    AGENT_DOCS_RULE_KEY,
    CLAUDE_AGENTS_RULE_KEY,
    CLAUDE_SKILLS_RULE_KEY,
    HUMAN_DOCS_RULE_KEY,
    PLAN_DIR_RULE_KEY,
    RULE_VERSION_MARKER_PREFIX,
    RULES_DIR_PARTS,
    SHIPPED_RULES,
    SOURCE_DIRS_RULE_KEY,
    TEST_DIRS_RULE_KEY,
    RuleAction,
    RuleAssetSpec,
    RuleAssetState,
    classify_rule,
    deploy_rule,
    deployed_rule_path,
    directory_roles_link,
    render_rule_content,
    rules_dir,
    spec_by_key,
    sync_directory_role_rules,
    sync_directory_role_rules_if_enabled,
)


def _spec(key: str) -> RuleAssetSpec:
    return spec_by_key(key)


class TestRegistry:
    def test_registry_contains_every_role(self) -> None:
        keys = {spec.key for spec in SHIPPED_RULES}
        assert keys == {
            SOURCE_DIRS_RULE_KEY,
            TEST_DIRS_RULE_KEY,
            HUMAN_DOCS_RULE_KEY,
            AGENT_DOCS_RULE_KEY,
            CLAUDE_SKILLS_RULE_KEY,
            CLAUDE_AGENTS_RULE_KEY,
            PLAN_DIR_RULE_KEY,
        }

    def test_spec_by_key_unknown_raises(self) -> None:
        import pytest

        with pytest.raises(KeyError):
            spec_by_key("no-such-role")

    def test_only_plan_dir_is_gated(self) -> None:
        for spec in SHIPPED_RULES:
            if spec.key == PLAN_DIR_RULE_KEY:
                assert spec.gating_config_key == "plan_workflow.enabled"
                assert not spec.is_enabled(Config())
                assert spec.is_enabled(Config.model_validate({"plan_workflow": {"enabled": True}}))
            else:
                assert spec.gating_config_key is None
                assert spec.is_enabled(Config())

    def test_every_body_template_has_the_link_placeholder(self) -> None:
        for spec in SHIPPED_RULES:
            assert "{directory_roles_link}" in spec.body_template


class TestDirectoryRolesLink:
    def test_self_install_mode_links_into_configured_agent_tree(self) -> None:
        config = Config.model_validate(
            {"daemon": {"self_install_mode": True}, "documentation": {"trees": {"agent": "CLAUDE"}}}
        )
        link = directory_roles_link(config)
        assert link == "../../CLAUDE/DirectoryRoles.md"

    def test_self_install_mode_respects_custom_agent_tree_name(self) -> None:
        config = Config.model_validate(
            {
                "daemon": {"self_install_mode": True},
                "documentation": {"trees": {"agent": "AgentDocs"}},
            }
        )
        link = directory_roles_link(config)
        assert link == "../../AgentDocs/DirectoryRoles.md"

    def test_normal_install_links_into_vendored_daemon_tree(self) -> None:
        config = Config.model_validate({"daemon": {"self_install_mode": False}})
        link = directory_roles_link(config)
        assert link == "../hooks-daemon/CLAUDE/DirectoryRoles.md"

    def test_normal_install_link_ignores_client_agent_tree_name(self) -> None:
        # The daemon's OWN doc tree is always named CLAUDE/, independent of
        # whatever the client configured for its own documentation.trees.agent.
        config = Config.model_validate(
            {
                "daemon": {"self_install_mode": False},
                "documentation": {"trees": {"agent": "AgentDocs"}},
            }
        )
        link = directory_roles_link(config)
        assert link == "../hooks-daemon/CLAUDE/DirectoryRoles.md"


class TestRenderRuleContent:
    def test_frontmatter_lists_every_glob(self) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        content = render_rule_content(spec, ("src/**/*.md", "lib/**/*.md"), "../../CLAUDE/x.md")
        assert '  - "src/**/*.md"' in content
        assert '  - "lib/**/*.md"' in content

    def test_includes_version_marker(self) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        content = render_rule_content(spec, ("src/**/*.md",), "../../CLAUDE/x.md")
        assert f"{RULE_VERSION_MARKER_PREFIX} {spec.version} -->" in content

    def test_body_link_is_substituted(self) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        content = render_rule_content(spec, ("src/**/*.md",), "../../CLAUDE/DirectoryRoles.md")
        assert "[DirectoryRoles.md](../../CLAUDE/DirectoryRoles.md)" in content

    def test_body_stays_within_the_rules_file_shape_line_budget(self) -> None:
        # R7a / rules-file-shape: 15 non-blank body lines, frontmatter
        # excluded. Every shipped rule must render well under budget.
        for spec in SHIPPED_RULES:
            content = render_rule_content(spec, ("x/**/*.md",), "../../CLAUDE/x.md")
            # Strip the frontmatter block the same way rules-file-shape does.
            body = content.split("---\n", 2)[-1]
            non_blank = [line for line in body.splitlines() if line.strip()]
            assert len(non_blank) <= 15, f"{spec.key}: {len(non_blank)} non-blank body lines"


class TestClassifyAndDeploy:
    def _config(self, tmp_path: Path, **overrides: object) -> Config:
        payload: dict[str, object] = {"plan_workflow": {"enabled": True}}
        payload.update(overrides)
        return Config.model_validate(payload)

    def test_absent_is_deployed(self, tmp_path: Path) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        config = self._config(tmp_path)
        assert classify_rule(spec, tmp_path, config) is RuleAssetState.ABSENT

        result = deploy_rule(spec, tmp_path, config)
        assert result.action is RuleAction.DEPLOYED
        assert deployed_rule_path(spec, tmp_path).is_file()

    def test_deployed_pristine_file_is_current(self, tmp_path: Path) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        config = self._config(tmp_path)
        deploy_rule(spec, tmp_path, config)

        assert classify_rule(spec, tmp_path, config) is RuleAssetState.CURRENT
        result = deploy_rule(spec, tmp_path, config)
        assert result.action is RuleAction.KEPT_CURRENT

    def test_config_drift_refreshes_globs_without_customisation_warning(
        self, tmp_path: Path
    ) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        config_before = self._config(tmp_path)
        deploy_rule(spec, tmp_path, config_before)

        config_after = self._config(tmp_path, layout={"source_dirs": ["app"], "mode": "replace"})
        assert classify_rule(spec, tmp_path, config_after) is RuleAssetState.OUTDATED

        result = deploy_rule(spec, tmp_path, config_after)
        assert result.action is RuleAction.REFRESHED
        content = deployed_rule_path(spec, tmp_path).read_text()
        assert '  - "app/**/*.md"' in content

    def test_customised_body_is_never_touched(self, tmp_path: Path) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        config = self._config(tmp_path)
        target = deployed_rule_path(spec, tmp_path)
        target.parent.mkdir(parents=True)
        target.write_text('---\npaths:\n  - "src/**/*.md"\ndescription: x\n---\n\nMy own rule.\n')

        assert classify_rule(spec, tmp_path, config) is RuleAssetState.CUSTOMISED
        result = deploy_rule(spec, tmp_path, config)
        assert result.action is RuleAction.CUSTOMISED_WARNING
        assert target.read_text() == (
            '---\npaths:\n  - "src/**/*.md"\ndescription: x\n---\n\nMy own rule.\n'
        )

    def test_plan_dir_rule_skipped_when_workflow_disabled(self, tmp_path: Path) -> None:
        config = Config()
        report = sync_directory_role_rules(tmp_path, config)
        plan_result = next(r for r in report.results if r.key == PLAN_DIR_RULE_KEY)
        assert plan_result.action is RuleAction.SKIPPED_DISABLED
        assert not deployed_rule_path(spec_by_key(PLAN_DIR_RULE_KEY), tmp_path).exists()

    def test_sync_deploys_every_non_gated_rule(self, tmp_path: Path) -> None:
        config = Config()
        report = sync_directory_role_rules(tmp_path, config)
        deployed_keys = {r.key for r in report.results if r.action is RuleAction.DEPLOYED}
        assert deployed_keys == {
            SOURCE_DIRS_RULE_KEY,
            TEST_DIRS_RULE_KEY,
            HUMAN_DOCS_RULE_KEY,
            AGENT_DOCS_RULE_KEY,
            CLAUDE_SKILLS_RULE_KEY,
            CLAUDE_AGENTS_RULE_KEY,
        }

    def test_sync_is_idempotent(self, tmp_path: Path) -> None:
        config = self._config(tmp_path)
        first = sync_directory_role_rules(tmp_path, config)
        second = sync_directory_role_rules(tmp_path, config)
        assert all(r.action is RuleAction.DEPLOYED for r in first.results)
        assert all(r.action is RuleAction.KEPT_CURRENT for r in second.results)


class TestSyncIfEnabled:
    def test_loads_config_and_deploys(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        report = sync_directory_role_rules_if_enabled(tmp_path, config_path)
        assert deployed_rule_path(spec_by_key(SOURCE_DIRS_RULE_KEY), tmp_path).is_file()
        assert any(r.key == SOURCE_DIRS_RULE_KEY for r in report.results)


class TestRulesDirHelpers:
    def test_rules_dir_matches_the_dir_parts_constant(self, tmp_path: Path) -> None:
        assert rules_dir(tmp_path) == tmp_path.joinpath(*RULES_DIR_PARTS)

    def test_deployed_rule_path_is_under_rules_dir(self, tmp_path: Path) -> None:
        spec = _spec(SOURCE_DIRS_RULE_KEY)
        path = deployed_rule_path(spec, tmp_path)
        assert path.parent == rules_dir(tmp_path)
        assert path.name == f"{spec.key}.md"


def test_module_importable() -> None:
    assert directory_role_rules.SHIPPED_RULES
