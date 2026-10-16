"""Plan 00495 Task 3.1: the start-up budget check's decision logic and its wiring.

``scripts/release/check_startup_budget.py`` measures the CPU a daemon start spends
before its socket is bound and fails when the median is over the budget recorded in
``CLAUDE/Performance/startup-budget.json``. These tests pin the decision logic with
injected samples (no daemon is started) and pin that the budget, the performance
README and the release procedure agree.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "release" / "check_startup_budget.py"
BUDGET_FILE = REPO_ROOT / "CLAUDE" / "Performance" / "startup-budget.json"
README = REPO_ROOT / "CLAUDE" / "Performance" / "README.md"
RELEASING = REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_startup_budget", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    return _load()


def _write_budget(path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {"cpu_seconds": 1.5, "samples": 3, "attempts": 2}
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadBudget:
    def test_reads_the_three_fields(self, mod: ModuleType, tmp_path: Path) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        assert (budget.cpu_seconds, budget.samples, budget.attempts) == (1.5, 3, 2)

    @pytest.mark.parametrize(
        "overrides",
        [{"cpu_seconds": 0}, {"cpu_seconds": -1.0}, {"samples": 0}, {"attempts": 0}],
    )
    def test_a_non_positive_value_is_refused(
        self, mod: ModuleType, tmp_path: Path, overrides: dict[str, object]
    ) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            mod.load_budget(_write_budget(tmp_path / "b.json", **overrides))

    def test_a_missing_field_is_refused(self, mod: ModuleType, tmp_path: Path) -> None:
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"cpu_seconds": 1.5}), encoding="utf-8")
        with pytest.raises(ValueError, match="samples"):
            mod.load_budget(path)

    def test_a_missing_file_is_refused(self, mod: ModuleType, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            mod.load_budget(tmp_path / "absent.json")


class TestEvaluate:
    def test_a_median_under_budget_passes(self, mod: ModuleType, tmp_path: Path) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        assert mod.evaluate([1.0, 1.1, 1.2], budget).passed is True

    def test_a_median_over_budget_fails(self, mod: ModuleType, tmp_path: Path) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        verdict = mod.evaluate([2.0, 2.1, 2.2], budget)
        assert verdict.passed is False
        assert verdict.median_cpu == pytest.approx(2.1)

    def test_one_slow_outlier_does_not_fail_the_median(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        assert mod.evaluate([1.0, 9.0, 1.1], budget).passed is True

    def test_a_median_exactly_at_budget_passes(self, mod: ModuleType, tmp_path: Path) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        assert mod.evaluate([1.5, 1.5, 1.5], budget).passed is True

    def test_no_samples_is_an_error_not_a_pass(self, mod: ModuleType, tmp_path: Path) -> None:
        budget = mod.load_budget(_write_budget(tmp_path / "b.json"))
        with pytest.raises(ValueError, match="no samples"):
            mod.evaluate([], budget)


class TestCheck:
    """``check`` retries a failing round: load noise passes on a retry, a slowdown does not."""

    def _budget(self, mod: ModuleType, tmp_path: Path) -> object:
        return mod.load_budget(_write_budget(tmp_path / "b.json"))

    def test_a_clean_first_round_is_the_only_round(self, mod: ModuleType, tmp_path: Path) -> None:
        rounds: list[int] = []

        def measure() -> float:
            rounds.append(1)
            return 1.0

        verdict = mod.check(self._budget(mod, tmp_path), measure)
        assert verdict.passed is True
        assert len(rounds) == 3  # one round of `samples`

    def test_a_noisy_first_round_passes_on_the_retry(self, mod: ModuleType, tmp_path: Path) -> None:
        readings = iter([3.0, 3.0, 3.0, 1.0, 1.0, 1.0])
        verdict = mod.check(self._budget(mod, tmp_path), lambda: next(readings))
        assert verdict.passed is True

    def test_a_planted_slowdown_fails_every_round(self, mod: ModuleType, tmp_path: Path) -> None:
        calls: list[int] = []

        def measure() -> float:
            calls.append(1)
            return 3.0

        verdict = mod.check(self._budget(mod, tmp_path), measure)
        assert verdict.passed is False
        assert len(calls) == 6  # `attempts` rounds of `samples`

    def test_a_measurement_failure_propagates(self, mod: ModuleType, tmp_path: Path) -> None:
        def measure() -> float:
            raise mod.MeasurementError("probe exited 1")

        with pytest.raises(mod.MeasurementError, match="probe exited 1"):
            mod.check(self._budget(mod, tmp_path), measure)


class TestTheShippedBudget:
    def test_the_budget_file_loads(self, mod: ModuleType) -> None:
        budget = mod.load_budget(BUDGET_FILE)
        assert budget.cpu_seconds > 0

    def test_the_readme_records_the_budget_value(self, mod: ModuleType) -> None:
        budget = mod.load_budget(BUDGET_FILE)
        assert f"{budget.cpu_seconds:g} s CPU" in README.read_text(encoding="utf-8")


class TestTheReleaseProcedureRunsIt:
    def test_the_check_runs_before_the_tag_is_created(self) -> None:
        text = RELEASING.read_text(encoding="utf-8")
        check = text.find("scripts/release/check_startup_budget.py")
        tag = text.find("git tag -a vX.Y.Z -m")
        assert check != -1, "RELEASING.md must run check_startup_budget.py"
        assert tag != -1
        assert check < tag, "the start-up budget check must run BEFORE the tag is created"

    def test_it_is_a_blocking_gate_in_the_pipeline_overview(self) -> None:
        text = RELEASING.read_text(encoding="utf-8")
        assert "Start-up Budget Gate" in text
