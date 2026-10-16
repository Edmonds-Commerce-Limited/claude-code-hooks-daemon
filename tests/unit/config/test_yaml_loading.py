"""Tests for the config YAML loader: C parser when present, never the unsafe loader."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from claude_code_hooks_daemon.config import yaml_loading
from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config


class TestConfigYamlLoaderSelection:
    """The loader class is chosen once, from what PyYAML was built with."""

    @pytest.mark.skipif(not yaml.__with_libyaml__, reason="PyYAML built without libyaml")
    def test_uses_c_safe_loader_when_libyaml_is_available(self) -> None:
        """With libyaml, the C-accelerated safe loader is selected."""
        assert yaml_loading.select_safe_loader() is yaml.CSafeLoader

    def test_falls_back_to_pure_python_safe_loader_without_libyaml(self) -> None:
        """Without libyaml the pure-Python SafeLoader is selected, not the unsafe one."""
        with patch.object(yaml_loading, "_C_SAFE_LOADER", None):
            assert yaml_loading.select_safe_loader() is yaml.SafeLoader

    def test_never_selects_an_unsafe_loader(self) -> None:
        """Whichever loader is chosen, it is a safe one."""
        loader = yaml_loading.select_safe_loader()
        assert loader in (yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        assert loader not in (yaml.Loader, yaml.FullLoader, yaml.UnsafeLoader)


class TestSafeLoadYaml:
    """``safe_load_yaml`` parses like ``yaml.safe_load``."""

    def test_parses_a_mapping(self) -> None:
        """A document parses to the same value ``yaml.safe_load`` gives."""
        text = "a: 1\nb:\n  - x\n  - y\nc: {d: true}\n"
        assert yaml_loading.safe_load_yaml(text) == yaml.safe_load(text)

    def test_empty_document_is_none(self) -> None:
        """An empty document is None, as with ``yaml.safe_load``."""
        assert yaml_loading.safe_load_yaml("") is None

    def test_python_object_tag_is_refused(self) -> None:
        """An arbitrary-object tag is a parse error, on either loader."""
        with pytest.raises(yaml.YAMLError):
            yaml_loading.safe_load_yaml("x: !!python/object/apply:os.getcwd []\n")

    def test_pure_python_fallback_parses_and_refuses_the_same(self) -> None:
        """The fallback loader gives the same value and the same refusal."""
        with patch.object(yaml_loading, "_C_SAFE_LOADER", None):
            assert yaml_loading.safe_load_yaml("a: [1, 2]\n") == {"a": [1, 2]}
            with pytest.raises(yaml.YAMLError):
                yaml_loading.safe_load_yaml("x: !!python/object/apply:os.getcwd []\n")

    def test_reads_a_text_stream(self, tmp_path: Path) -> None:
        """An open file is accepted as well as a string."""
        path = tmp_path / "c.yaml"
        path.write_text("k: v\n", encoding="utf-8")
        with path.open() as handle:
            assert yaml_loading.safe_load_yaml(handle) == {"k": "v"}


class TestConfigReadersUseTheSharedLoader:
    """Both start-path config readers parse through ``safe_load_yaml``."""

    def test_config_load_uses_it(self, tmp_path: Path) -> None:
        """``Config.load`` parses through the shared loader."""
        path = tmp_path / "hooks-daemon.yaml"
        path.write_text("version: '2.0'\n", encoding="utf-8")
        with patch(
            "claude_code_hooks_daemon.config.models.safe_load_yaml",
            wraps=yaml_loading.safe_load_yaml,
        ) as spy:
            Config.load(path)
        assert spy.call_count == 1

    def test_config_loader_load_uses_it(self, tmp_path: Path) -> None:
        """``ConfigLoader.load`` parses through the shared loader."""
        path = tmp_path / "hooks-daemon.yaml"
        path.write_text("version: '2.0'\n", encoding="utf-8")
        with patch(
            "claude_code_hooks_daemon.config.loader.safe_load_yaml",
            wraps=yaml_loading.safe_load_yaml,
        ) as spy:
            assert ConfigLoader.load(path) == {"version": "2.0"}
        assert spy.call_count == 1
