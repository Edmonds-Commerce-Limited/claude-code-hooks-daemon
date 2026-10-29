"""Tests for daemon/init_config.py."""

from unittest.mock import patch

from claude_code_hooks_daemon.daemon.init_config import (
    ConfigTemplate,
    _get_enforcement_line,
    generate_config,
)


class TestGetEnforcementLine:
    """Tests for _get_enforcement_line helper."""

    def test_returns_commented_out_line_when_not_in_container(self) -> None:
        """Returns commented-out enforcement line when not in a container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            line = _get_enforcement_line()

        assert line.startswith("  #")
        assert "enforce_single_daemon_process" in line

    def test_returns_enabled_line_when_in_container(self) -> None:
        """Returns enabled enforcement line when running in a container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            line = _get_enforcement_line()

        assert "enforce_single_daemon_process: true" in line
        assert not line.startswith("  #")

    def test_enforcement_line_autoenabled_when_lxc_detected(self) -> None:
        """Plan 00127 Phase 4: LXC now drives is_container_environment() True.

        Patches the real detection chain (detect_container_runtime → 'lxc')
        rather than mocking is_container_environment directly, proving an LXC
        host auto-enables single-daemon enforcement at config-generation time.
        """
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.detect_container_runtime",
            return_value="lxc",
        ):
            line = _get_enforcement_line()

        assert (
            line == "  enforce_single_daemon_process: true   # Auto-enabled (container detected)\n"
        )


class TestConfigTemplate:
    """Tests for ConfigTemplate.generate_minimal and generate_full."""

    def test_generate_minimal_returns_yaml_string(self) -> None:
        """generate_minimal returns a valid YAML config string."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = ConfigTemplate.generate_minimal()

        assert 'version: "1.0"' in result
        assert "daemon:" in result
        assert "handlers:" in result

    def test_generate_full_returns_yaml_string(self) -> None:
        """generate_full returns a more complete YAML config string."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = ConfigTemplate.generate_full()

        assert 'version: "1.0"' in result
        assert "pre_tool_use:" in result
        assert "post_tool_use:" in result

    def test_both_templates_document_collect_all_violations_off(self) -> None:
        """daemon.chain.collect_all_violations (Plan 00242) ships documented and OFF."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            for template in (ConfigTemplate.generate_minimal(), ConfigTemplate.generate_full()):
                assert "  chain:\n" in template
                assert "collect_all_violations: false" in template

    def test_generate_minimal_in_container_enables_enforcement(self) -> None:
        """generate_minimal includes enabled enforcement line in container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            result = ConfigTemplate.generate_minimal()

        assert "enforce_single_daemon_process: true" in result

    def test_generate_full_in_container_enables_enforcement(self) -> None:
        """generate_full includes enabled enforcement line in container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            result = ConfigTemplate.generate_full()

        assert "enforce_single_daemon_process: true" in result

    def test_client_template_ships_empty_tier_tables(self) -> None:
        """Plan 00472 rulings D2/D3: clients get no ceilings or floors, advise mode only."""
        import yaml

        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            config = yaml.safe_load(ConfigTemplate.generate_full())
        options = config["handlers"]["pre_tool_use"]["subagent_tier_advisor"]["options"]
        assert options == {
            "mode": "advise",
            "default_ceiling": None,
            "types": {},
            "role_floors": {},
        }

    def test_both_templates_leave_relay_enabled_to_the_host_default(self) -> None:
        """A new config names no relay_enabled, so the host-aware model default decides."""
        import yaml

        from claude_code_hooks_daemon.config.models import TransportConfig
        from claude_code_hooks_daemon.utils.relay_host import relay_supported_by_host

        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            templates = (ConfigTemplate.generate_minimal(), ConfigTemplate.generate_full())
        for template in templates:
            transport = yaml.safe_load(template)["daemon"]["transport"]
            assert "relay_enabled" not in transport
            parsed = TransportConfig.model_validate(transport)
            assert parsed.relay_enabled is relay_supported_by_host()
            assert parsed.relay_source == "auto"

    def test_the_model_default_follows_the_host(self) -> None:
        """The model default is host-aware: relay where a binary can run, provisioned by auto."""
        from claude_code_hooks_daemon.config.models import TransportConfig
        from claude_code_hooks_daemon.utils.relay_host import relay_supported_by_host

        assert TransportConfig().relay_enabled is relay_supported_by_host()
        assert TransportConfig().relay_source == "auto"

    def test_plugins_block_is_labelled_as_daemon_plugins(self) -> None:
        """Both templates say the `plugins:` block holds daemon plugins, so a
        client never mistakes it for Claude Code plugins (Plan 00468 G5)."""
        label = "# Daemon plugins: custom handler modules (not Claude Code plugins)\nplugins:\n"
        assert label in ConfigTemplate.generate_minimal()
        assert label in ConfigTemplate.generate_full()


class TestGenerateConfig:
    """Tests for generate_config convenience function."""

    def test_generate_config_minimal_mode(self) -> None:
        """generate_config with 'minimal' returns minimal template."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config("minimal")

        assert 'version: "1.0"' in result
        # Minimal should not have per-handler entries
        assert "destructive_git" not in result

    def test_generate_config_full_mode(self) -> None:
        """generate_config with 'full' returns full template."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config("full")

        assert "destructive_git" in result

    def test_generate_config_defaults_to_full(self) -> None:
        """generate_config defaults to full mode."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config()

        assert "destructive_git" in result
