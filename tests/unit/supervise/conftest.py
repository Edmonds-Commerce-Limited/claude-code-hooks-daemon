"""Shared fixtures for the ccy supervisor unit tests.

Hermeticity against ambient ``CCY_FLAG_COMPACT`` (dogfooding fix). The
supervisor reads this toggle from the process environment at ``CompactPolicy``
construction time (``_flag_compact_enabled_from_env``), so any test that builds
a policy via the default factory inherits whatever the ambient shell exports. A
ccy-supervised dogfooding session exports ``CCY_FLAG_COMPACT=1`` (Plan 00281),
which made ``test_effort_restore.py::test_model_restore_cap`` pass in CI (the
var is unset there) yet fail in-session (the var is set): the flag-cleaning
``/compact`` path fired past the model-restore cap that test asserts silence
at. The failure was environmental, not a product defect — the two features are
independent — but a unit test must not depend on the ambient shell.

Clearing the var by default makes every supervise test hermetic. The dedicated
flag-compact tests opt in explicitly — ``CompactPolicy(flag_compact_enabled=
True)`` or their own ``monkeypatch.setenv`` — and this fixture runs first, so
their explicit setup still wins.
"""

from __future__ import annotations

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()


@pytest.fixture(autouse=True)
def _neutralise_ambient_flag_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ambient ``CCY_FLAG_COMPACT`` so tests default to the shipped-off state."""
    monkeypatch.delenv(_mod._FLAG_COMPACT_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def _isolate_worker_error_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Point the worker error log at a per-test temp file (dogfooding fix).

    ``worker_error_log_path()`` resolves the LIVE daemon untracked dir, so any
    test exercising a code path that calls ``append_worker_error`` appends to
    the running session's own worker log — polluting field diagnostics with
    test-session ids and fabricated 'observed' events. Redirecting here makes
    that structurally impossible. The dedicated worker-error tests override
    this symbol explicitly and, as with the fixture above, their setup wins
    because it runs after this one.
    """
    sink = tmp_path_factory.mktemp("worker-error-log") / "worker.err.log"
    monkeypatch.setattr(_mod, "worker_error_log_path", lambda: sink)
