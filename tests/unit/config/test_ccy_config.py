"""Unit tests for CcyConfig model (Plan 00147).

The ``ccy.deploy_supervisor`` flag is tri-state:

- ``True``  — deploy/refresh the supervisor when a ``.claude/ccy/`` dir exists
- ``False`` — never deploy (explicit opt-out)
- ``None``  — (absent from config) deploy anyway + recommend enabling

so ``deploy_supervisor`` is ``bool | None`` and the model must faithfully
round-trip the absence of the key as ``None`` (never coerced to ``False``).
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import CcyConfig, Config


class TestCcyConfigDefaults:
    """Test CcyConfig default values."""

    def test_default_deploy_supervisor_is_none(self) -> None:
        """Absent flag defaults to None (tri-state 'not configured')."""
        config = CcyConfig()
        assert config.deploy_supervisor is None

    def test_deploy_supervisor_true(self) -> None:
        """Explicit True is preserved."""
        config = CcyConfig(deploy_supervisor=True)
        assert config.deploy_supervisor is True

    def test_deploy_supervisor_false(self) -> None:
        """Explicit False is preserved (opt-out)."""
        config = CcyConfig(deploy_supervisor=False)
        assert config.deploy_supervisor is False


class TestCcyConfigValidation:
    """Test CcyConfig validation."""

    def test_extra_fields_are_rejected(self) -> None:
        """Unknown fields raise ValidationError (extra='forbid' catches typos)."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CcyConfig(deploy_supervisor=True, typo_field="oops")

    def test_deploy_supervisor_rejects_non_bool(self) -> None:
        """A non-bool, non-null value is rejected."""
        with pytest.raises(ValidationError):
            CcyConfig(deploy_supervisor="yes-please")


class TestCcyConfigInRootConfig:
    """Test CcyConfig integration with the root Config model."""

    def test_root_config_has_ccy_field(self) -> None:
        config = Config()
        assert hasattr(config, "ccy")
        assert isinstance(config.ccy, CcyConfig)

    def test_root_config_default_ccy_is_none(self) -> None:
        config = Config()
        assert config.ccy.deploy_supervisor is None

    def test_root_config_ccy_from_dict(self) -> None:
        config = Config.model_validate({"version": "2.0", "ccy": {"deploy_supervisor": True}})
        assert config.ccy.deploy_supervisor is True

    def test_root_config_ccy_false_from_dict(self) -> None:
        config = Config.model_validate({"version": "2.0", "ccy": {"deploy_supervisor": False}})
        assert config.ccy.deploy_supervisor is False

    def test_root_config_ccy_from_yaml(self, tmp_path: Path) -> None:
        config_data = {"version": "2.0", "ccy": {"deploy_supervisor": True}}
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(yaml.safe_dump(config_data))

        config = Config.load(config_file)
        assert config.ccy.deploy_supervisor is True

    def test_root_config_missing_ccy_uses_defaults(self) -> None:
        """Absent ccy section → default CcyConfig with deploy_supervisor None."""
        config = Config.model_validate({"version": "2.0"})
        assert config.ccy.deploy_supervisor is None

    def test_root_config_serializes_ccy(self) -> None:
        config = Config(ccy=CcyConfig(deploy_supervisor=True))
        parsed = yaml.safe_load(config.to_yaml())
        assert "ccy" in parsed
        assert parsed["ccy"]["deploy_supervisor"] is True
