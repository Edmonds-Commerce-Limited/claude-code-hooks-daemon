"""The remote_docs package imports cleanly (Plan 00326).

A package marker has no logic of its own, but it does have one failure mode
worth a test: a broken or missing ``__init__`` makes every module under it
unimportable, and the first symptom is an unrelated handler failing at
runtime rather than here.
"""

import importlib


def test_package_imports() -> None:
    module = importlib.import_module("claude_code_hooks_daemon.remote_docs")

    assert module.__doc__ is not None


def test_provenance_module_is_reachable_through_the_package() -> None:
    module = importlib.import_module("claude_code_hooks_daemon.remote_docs.provenance")

    assert hasattr(module, "parse_provenance")
