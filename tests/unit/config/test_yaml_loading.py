"""Tests for the config YAML loader: C parser when present, never the unsafe loader."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from claude_code_hooks_daemon.config import yaml_loading
from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import Timeout


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


class TestDeepNestingNeverReachesTheCParser:
    """libyaml composes nesting recursively in C, with no recursion limit."""

    def test_a_flow_document_nested_past_the_c_stack_raises_instead_of_crashing(self) -> None:
        """A document deep enough to overflow libyaml's C stack must raise
        RecursionError (which ``Config.load`` turns into ValueError), not kill
        the process. Run in a child so a crash fails this test, not the run."""
        program = (
            "from claude_code_hooks_daemon.config.yaml_loading import safe_load_yaml\n"
            "depth = 100_000\n"
            "try:\n"
            "    safe_load_yaml('[' * depth + ']' * depth)\n"
            "except RecursionError:\n"
            "    print('RecursionError')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "RecursionError"

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param("- " * 100_000 + "x\n", id="inline-block-sequences"),
            pytest.param("? " * 100_000 + "x\n", id="inline-complex-keys"),
            pytest.param("- " * 50_000 + "[" * 50_000 + "]" * 50_000 + "\n", id="mixed"),
        ],
    )
    def test_block_nesting_past_the_c_stack_raises_instead_of_crashing(self, document: str) -> None:
        """``- - - ...`` nests one level per two characters with no brackets at all,
        so it reaches libyaml's C recursion unless the routing counts it too. Run
        in a child so a segfault fails this test rather than killing pytest."""
        program = (
            "import sys\n"
            "from claude_code_hooks_daemon.config.yaml_loading import safe_load_yaml\n"
            "try:\n"
            "    safe_load_yaml(sys.stdin.read())\n"
            "except RecursionError:\n"
            "    print('RecursionError')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            input=document,
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
        )
        assert completed.returncode == 0, f"exit {completed.returncode}: {completed.stderr}"
        assert completed.stdout.strip() == "RecursionError"

    def test_deep_indentation_uses_the_pure_python_loader(self) -> None:
        """Mapping nesting by indentation is bounded by the widest indent."""
        depth = yaml_loading.C_LOADER_MAX_OPEN_BRACKETS + 1
        text = "".join(f"{' ' * level}k{level}:\n" for level in range(depth)) + " " * depth + "v\n"
        with patch.object(yaml_loading.yaml, "SafeLoader", wraps=yaml.SafeLoader) as spy:
            with pytest.raises(RecursionError):
                yaml_loading.safe_load_yaml(text)
        assert spy.call_count == 1

    def test_deep_inline_block_indicators_use_the_pure_python_loader(self) -> None:
        """A line led by more indicators than the budget never reaches libyaml,
        whichever line break ends the line before it."""
        budget = yaml_loading.C_LOADER_MAX_OPEN_BRACKETS
        for separator in ("\n", "\r", "\r\n"):
            text = f"a: 1{separator}" + "- " * budget + "x\n"
            with patch.object(yaml_loading.yaml, "SafeLoader", wraps=yaml.SafeLoader) as spy:
                with pytest.raises(yaml.YAMLError):
                    yaml_loading.safe_load_yaml(text)
            assert spy.call_count == 1, repr(separator)

    def test_a_document_over_the_bracket_budget_uses_the_pure_python_loader(self) -> None:
        """Flow depth cannot exceed the count of opening brackets, so a document
        with more than the budget is parsed where depth is bounded."""
        budget = yaml_loading.C_LOADER_MAX_OPEN_BRACKETS
        text = "a: [" + ", ".join("[1]" for _ in range(budget)) + "]\n"
        with patch.object(yaml_loading.yaml, "SafeLoader", wraps=yaml.SafeLoader) as spy:
            assert len(yaml_loading.safe_load_yaml(text)["a"]) == budget
        assert spy.call_count == 1

    @pytest.mark.skipif(not yaml.__with_libyaml__, reason="PyYAML built without libyaml")
    def test_an_ordinary_config_stays_on_the_c_loader(self) -> None:
        """This repository's own config is far under the budget."""
        config = Path(__file__).resolve().parents[3] / ".claude" / "hooks-daemon.yaml"
        with patch.object(yaml_loading, "_C_SAFE_LOADER", wraps=yaml.CSafeLoader) as spy:
            yaml_loading.safe_load_yaml(config.read_text(encoding="utf-8"))
        assert spy.call_count == 1


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
