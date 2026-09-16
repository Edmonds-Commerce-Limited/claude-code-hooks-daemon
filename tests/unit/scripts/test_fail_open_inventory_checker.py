"""The `fail-open-inventory` Detector — Plan 00412 class 4 (Defence Before Fix).

The class: **the guarded action proceeds when the guard could not reach a
verdict**, and in several instances the party the guard constrains can induce
the condition. "Make the guard slow, and the guard is skipped."

Why this Defence is an inventory rather than a code rule: the discriminator is
a property of the *surface*, not of the code. `sensitive_content`'s staged-diff
stand-down and its `gh`-body stand-down are the same shape, and one is
defensible while the other is not — because a commit can be amended before it
is pushed and a published comment cannot be recalled. No regex sees that. So
the Detector enumerates candidates mechanically and the inventory carries the
judgement, one row per candidate, written by someone who looked.

Two properties the tests below exist to hold:

- **The narrowing predicate must discriminate.** A handler that re-raises is
  not a fail-open boundary, and if the scanner cannot tell the two apart then
  the inventory is a list of every `except` in the file and nobody fills it in
  honestly. A test that only ever feeds it swallowing handlers would pass
  against a scanner that flags all of them, so the re-raising control is the
  test that carries the evidence.
- **A rotted row must FAIL, not pass.** A row naming a boundary that no longer
  exists is the failure an inventory exists to prevent: it reads as coverage.

The third column — what trace the boundary leaves in-band — is the one F-BYPS
names as valuable, and several of these boundaries currently leave only a
stderr line. It is required of every `fail-open` row for that reason.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_fail_open_inventory.py"
_INVENTORY = _REPO_ROOT / "scripts" / "qa" / "fail-open-boundaries.yaml"

_PY_SURFACE = "src/claude_code_hooks_daemon/core/chain.py"
_RUST_SURFACE = "relay/hooks_relay.rs"
_SHELL_SURFACE = "init.sh"

#: Every surface the Detector scans. A synthetic tree must contain all of them:
#: a MISSING surface is itself a violation, because a scope that has quietly
#: stopped being scanned is the failure this Defence exists to prevent.
_ALL_PY_SURFACES = (
    _PY_SURFACE,
    "src/claude_code_hooks_daemon/core/front_controller.py",
    "src/claude_code_hooks_daemon/daemon/controller.py",
)


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_fail_open_inventory", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _surface(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _inventory(root: Path, body: str) -> Path:
    path = root / "inventory.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _empty_surfaces(root: Path) -> None:
    """Every surface present and boundary-free, so one test varies one thing."""
    for relative in _ALL_PY_SURFACES:
        _surface(root, relative, "def execute() -> None:\n    return None\n")
    _surface(root, _RUST_SURFACE, "fn main() {}\n")
    _surface(root, _SHELL_SURFACE, "#!/usr/bin/env bash\necho hello\n")


_SWALLOWING = """
import logging

logger = logging.getLogger(__name__)


def execute() -> None:
    try:
        run()
    except Exception:
        logger.exception("handler crashed")
"""

_RERAISING = """
import logging

logger = logging.getLogger(__name__)


def execute() -> None:
    try:
        run()
    except Exception:
        logger.exception("handler crashed")
        raise
"""


class TestPythonBoundaries:
    def test_an_undeclared_swallowing_handler_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _empty_surfaces(tmp_path)
        _surface(tmp_path, _PY_SURFACE, _SWALLOWING)
        inventory = _inventory(tmp_path, "boundaries: []\n")

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert violations[0].surface == _PY_SURFACE
        assert violations[0].scope == "execute"

    def test_a_handler_that_reraises_is_not_a_boundary(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The control that makes the test above evidence.

        Identical source but for the `raise`. If this reports a violation the
        scanner is flagging every `except` it sees, and the sibling test proved
        nothing about the narrowing.
        """
        _empty_surfaces(tmp_path)
        _surface(tmp_path, _PY_SURFACE, _RERAISING)
        inventory = _inventory(tmp_path, "boundaries: []\n")

        assert checker.scan(tmp_path, inventory) == []

    def test_a_declared_boundary_is_clean(self, checker: ModuleType, tmp_path: Path) -> None:
        _empty_surfaces(tmp_path)
        _surface(tmp_path, _PY_SURFACE, _SWALLOWING)
        inventory = _inventory(
            tmp_path,
            f"""
boundaries:
  - surface: {_PY_SURFACE}
    scope: execute
    construct: "except Exception"
    ordinal: 0
    verdict: fail-open
    induced_by: "any handler raising"
    caller_controlled: true
    trace: "logger.exception in the daemon log; nothing in-band"
""",
        )

        assert checker.scan(tmp_path, inventory) == []

    def test_two_handlers_in_one_scope_need_two_rows(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`chain.execute` really does carry two `except Exception` handlers.

        They are told apart by ordinal, so one row cannot silently cover both.
        """
        _empty_surfaces(tmp_path)
        _surface(
            tmp_path,
            _PY_SURFACE,
            """
import logging

logger = logging.getLogger(__name__)


def execute() -> None:
    try:
        run()
    except Exception:
        logger.exception("one")
    try:
        commit()
    except Exception:
        logger.exception("two")
""",
        )
        inventory = _inventory(
            tmp_path,
            f"""
boundaries:
  - surface: {_PY_SURFACE}
    scope: execute
    construct: "except Exception"
    ordinal: 0
    verdict: fail-open
    induced_by: "any handler raising"
    caller_controlled: true
    trace: "daemon log only"
""",
        )

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert violations[0].ordinal == 1


class TestRowQuality:
    def test_a_fail_open_row_without_a_trace_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Column three is the one F-BYPS names as valuable."""
        _empty_surfaces(tmp_path)
        _surface(tmp_path, _PY_SURFACE, _SWALLOWING)
        inventory = _inventory(
            tmp_path,
            f"""
boundaries:
  - surface: {_PY_SURFACE}
    scope: execute
    construct: "except Exception"
    ordinal: 0
    verdict: fail-open
    induced_by: "any handler raising"
    caller_controlled: true
    trace: "   "
""",
        )

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert "trace" in violations[0].detail

    def test_a_dismissal_without_a_reason_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """`not-fail-open` is a judgement, and an unexplained one cannot be reviewed."""
        _empty_surfaces(tmp_path)
        _surface(tmp_path, _PY_SURFACE, _SWALLOWING)
        inventory = _inventory(
            tmp_path,
            f"""
boundaries:
  - surface: {_PY_SURFACE}
    scope: execute
    construct: "except Exception"
    ordinal: 0
    verdict: not-fail-open
""",
        )

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert "reason" in violations[0].detail

    def test_a_row_naming_a_boundary_that_no_longer_exists_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Registry rot fails loudly.

        A row whose boundary has been deleted or renamed otherwise reads as a
        row that passes, which is the exact failure an inventory prevents.
        """
        _empty_surfaces(tmp_path)
        inventory = _inventory(
            tmp_path,
            f"""
boundaries:
  - surface: {_PY_SURFACE}
    scope: long_gone
    construct: "except Exception"
    ordinal: 0
    verdict: fail-open
    induced_by: "something"
    caller_controlled: false
    trace: "daemon log"
""",
        )

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert "no longer" in violations[0].detail

    def test_a_surface_that_has_vanished_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A scope that stopped being scanned must not read as a scope with nothing in it."""
        _empty_surfaces(tmp_path)
        (tmp_path / _RUST_SURFACE).unlink()
        inventory = _inventory(tmp_path, "boundaries: []\n")

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert violations[0].surface == _RUST_SURFACE
        assert "unreadable" in violations[0].detail


class TestNonPythonSurfaces:
    def test_an_undeclared_diverging_fail_funnel_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The relay's fail-open funnels are spelled `-> !`."""
        _empty_surfaces(tmp_path)
        _surface(
            tmp_path,
            _RUST_SURFACE,
            'fn mid_exchange_fail(detail: &str) -> ! {\n    eprintln!("{detail}");\n'
            "    process::exit(0);\n}\n",
        )
        inventory = _inventory(tmp_path, "boundaries: []\n")

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert violations[0].scope == "mid_exchange_fail"

    def test_an_ordinary_rust_function_is_not_a_boundary(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The control: a function that returns normally is not a fail funnel."""
        _empty_surfaces(tmp_path)
        _surface(
            tmp_path,
            _RUST_SURFACE,
            "fn classify(err: &io::Error) -> FailClass {\n    FailClass::Io\n}\n",
        )
        inventory = _inventory(tmp_path, "boundaries: []\n")

        assert checker.scan(tmp_path, inventory) == []

    def test_an_undeclared_shell_suppression_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _empty_surfaces(tmp_path)
        _surface(
            tmp_path,
            _SHELL_SURFACE,
            '#!/usr/bin/env bash\nwrite_forwarder() {\n  chmod +x "$f" 2>/dev/null\n}\n',
        )
        inventory = _inventory(tmp_path, "boundaries: []\n")

        violations = checker.scan(tmp_path, inventory)

        assert len(violations) == 1
        assert violations[0].scope == "write_forwarder"

    def test_plain_shell_is_not_a_boundary(self, checker: ModuleType, tmp_path: Path) -> None:
        _empty_surfaces(tmp_path)
        _surface(
            tmp_path,
            _SHELL_SURFACE,
            '#!/usr/bin/env bash\nwrite_forwarder() {\n  chmod +x "$f"\n}\n',
        )
        inventory = _inventory(tmp_path, "boundaries: []\n")

        assert checker.scan(tmp_path, inventory) == []


class TestDenominator:
    def test_a_clean_result_reports_how_many_boundaries_were_scanned(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Class 5's lesson, applied to this Detector's own output.

        "No violations" and "nothing was scanned" must not render identically,
        so the count is part of the result rather than something a reader infers
        from silence.
        """
        _empty_surfaces(tmp_path)

        assert checker.count_boundaries(tmp_path) == 0

        _surface(tmp_path, _PY_SURFACE, _SWALLOWING)

        assert checker.count_boundaries(tmp_path) == 1


class TestRealTree:
    def test_the_real_inventory_covers_the_real_enforcement_path(self, checker: ModuleType) -> None:
        """The Detector against this repository, which is the point of it."""
        violations = checker.scan(_REPO_ROOT, _INVENTORY)

        assert violations == [], "\n".join(
            f"{v.surface}::{v.scope}::{v.construct}#{v.ordinal}: {v.detail}" for v in violations
        )

    def test_the_real_enforcement_path_has_boundaries_to_find(self, checker: ModuleType) -> None:
        """Vacuity control for the test above.

        If the scanner found nothing in the real tree, a passing inventory check
        would be measuring an empty set — the absence of a complaint is only
        evidence if the checker actually ran on something.
        """
        assert checker.count_boundaries(_REPO_ROOT) > 0
