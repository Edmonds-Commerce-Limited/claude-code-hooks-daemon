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

import json
import os
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()


def write_attributed_downgrade(
    sidecar_dir: Path,
    *,
    session_id: str,
    original_family: str = "fable",
    fallback_family: str = "opus",
) -> Path:
    """Write the `.model-downgrade` signal the daemon's recorder publishes.

    Since Plan 00328 a downgrade episode opens ONLY for a drop Claude Code
    itself recorded, so any test that means "the safety classifier substituted
    the model" has to say so. Tests that mean "the human changed model"
    deliberately do NOT call this — that is the distinction the plan exists to
    draw, and leaving it implicit is what let the supervisor override a human
    in the field.
    """
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}{_mod._MODEL_DOWNGRADE_SIGNAL_SUFFIX}"
    path.write_text(
        json.dumps(
            {
                "ts": 0.0,
                "session_id": session_id,
                "original_model": f"claude-{original_family}-5",
                "fallback_model": f"claude-{fallback_family}-5",
                "original_family": original_family,
                "fallback_family": fallback_family,
                "category": "cyber",
                "scope": "session",
                "record_ts": "2026-08-27T09:34:10.341Z",
            }
        ),
        encoding="utf-8",
    )
    return path


AMBIENT_ENV_PREFIXES = ("CCY_", "CLAUDE_SUPERVISE_")


@pytest.fixture(autouse=True)
def _neutralise_ambient_ccy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every ambient supervisor variable so tests see the shipped defaults.

    A ccy session exports its own tuning (``CCY_MIN_EFFORT_LEVELS``,
    ``CCY_FLAG_COMPACT``, ...), which the supervisor reads at decision time.
    Clearing the whole namespace, not one named variable, is what keeps a new
    tunable from reintroducing the in-session-only failure (00466 N63).
    """
    for name in list(os.environ):
        if name.startswith(AMBIENT_ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


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
