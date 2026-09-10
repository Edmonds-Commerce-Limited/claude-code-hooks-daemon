"""The lsp_noise strategy package imports cleanly."""

import importlib


def test_package_imports() -> None:
    module = importlib.import_module("claude_code_hooks_daemon.strategies.lsp_noise")
    assert module is not None
