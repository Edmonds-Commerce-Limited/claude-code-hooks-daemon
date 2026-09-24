"""``handler_options``: the one reader of a handler block's ``options`` mapping.

Plan 00466 N14. A handler block reaches its readers in two shapes -- a
``HandlerConfig`` once ``Config`` has validated it, a plain dict wherever raw
YAML is read -- and a reader written for one shape finds nothing in the other
and silently falls back to defaults. Log and payload redaction did exactly
that, and ``secret_file_matching`` had done it before. The accessor tests pin
both shapes; the source scan pins that nothing in ``src/`` reads the key by
hand again.
"""

import ast
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import Config, HandlerConfig, handler_options
from claude_code_hooks_daemon.constants import ConfigKey

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "claude_code_hooks_daemon"
_ACCESSOR_MODULE = _SRC_ROOT / "config" / "models.py"
_ACCESSOR_NAME = "handler_options"


class TestHandlerOptionsAccessor:
    def test_reads_a_validated_handler_config(self) -> None:
        block = HandlerConfig(options={"secret_word_list_path": "a/b.txt"})
        assert handler_options(block) == {"secret_word_list_path": "a/b.txt"}

    def test_reads_a_raw_yaml_dict(self) -> None:
        block = {"enabled": True, "options": {"secret_word_list_path": "a/b.txt"}}
        assert handler_options(block) == {"secret_word_list_path": "a/b.txt"}

    def test_a_block_loaded_through_config_is_read(self) -> None:
        """The shape every daemon-side reader actually receives."""
        config = Config.model_validate(
            {
                "version": "1.0",
                "handlers": {
                    "pre_tool_use": {
                        "sensitive_content": {"options": {"secret_word_list_path": "x/y"}}
                    }
                },
            }
        )
        block = config.handlers.pre_tool_use.get("sensitive_content")
        assert isinstance(block, HandlerConfig)
        assert handler_options(block) == {"secret_word_list_path": "x/y"}

    @pytest.mark.parametrize(
        "block",
        [
            None,
            {},
            {"enabled": False},
            {"options": None},
            {"options": ["not", "a", "mapping"]},
            "a bare string",
            HandlerConfig(),
        ],
    )
    def test_anything_without_an_options_mapping_reads_as_empty(self, block: object) -> None:
        assert handler_options(block) == {}

    def test_returns_the_stored_mapping_not_a_copy(self) -> None:
        """The registry adds ``workspace_root`` to the mapping it reads."""
        stored: dict[str, object] = {"key": "value"}
        assert handler_options({"options": stored}) is stored
        block = HandlerConfig(options={"key": "value"})
        assert handler_options(block) is block.options


def _is_options_key(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == ConfigKey.OPTIONS
    return isinstance(node, ast.Attribute) and node.attr == "OPTIONS"


def _hand_reads_of_options(tree: ast.AST) -> list[int]:
    """Line numbers where ``options`` is read off a mapping or by ``getattr``.

    A typed ``block.options`` attribute read is not reported: it cannot
    silently miss a dict, it raises on one.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and _is_options_key(node.args[0])
        ):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and _is_options_key(node.args[1])
        ):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_options_key(node.slice)
        ):
            lines.append(node.lineno)
    return sorted(lines)


def _accessor_body_lines(tree: ast.Module) -> range:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == _ACCESSOR_NAME:
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            return range(node.lineno, end + 1)
    raise AssertionError(f"{_ACCESSOR_NAME} is missing from {_ACCESSOR_MODULE}")


def test_no_source_file_reads_handler_options_by_hand() -> None:
    """Every read of a handler block's ``options`` goes through the accessor."""
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        allowed = _accessor_body_lines(tree) if path == _ACCESSOR_MODULE else range(0)
        for line in _hand_reads_of_options(tree):
            if line not in allowed:
                offenders.append(f"{path.relative_to(_SRC_ROOT)}:{line}")
    assert offenders == [], (
        "Read handler options through config.models.handler_options, which "
        "accepts both a HandlerConfig and a raw dict: " + ", ".join(offenders)
    )


def test_no_source_file_binds_a_local_that_shadows_the_accessor() -> None:
    """A local named after the accessor makes every call in that function raise.

    ``HandlerRegistry.register_all`` bound one in its second pass, so the
    first pass's call raised ``UnboundLocalError`` -- and the broad ``except``
    around it logged at debug and dropped every handler's options.
    """
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if node.id == _ACCESSOR_NAME:
                    offenders.append(f"{path.relative_to(_SRC_ROOT)}:{node.lineno}")
            if isinstance(node, ast.arg) and node.arg == _ACCESSOR_NAME:
                offenders.append(f"{path.relative_to(_SRC_ROOT)}:{node.lineno}")
    assert offenders == [], f"rename these so they do not shadow the accessor: {offenders}"


def test_the_scan_catches_each_hand_read_shape() -> None:
    """The pin is only as good as its detector, so exercise the detector."""
    source = (
        "a = block.get('options', {})\n"
        "b = block.get(ConfigKey.OPTIONS)\n"
        "c = getattr(block, 'options', None)\n"
        "d = block['options']\n"
        "e = block.options\n"
        "block['options'] = {}\n"
    )
    assert _hand_reads_of_options(ast.parse(source)) == [1, 2, 3, 4]
