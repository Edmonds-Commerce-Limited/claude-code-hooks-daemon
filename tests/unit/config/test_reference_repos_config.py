"""The `reference_repos` config block (Plan 00401 Task 2.1).

The defaults carry the owner's three rulings, so they are asserted individually
rather than as one blob — a default that silently drifts turns a ruling into a
suggestion.

One default deserves its own justification: ``enabled`` ships TRUE. That is safe
precisely because discovery finds nothing when the configured root does not
exist, so a project that has never adopted the convention gets silence with no
config at all. Shipping it disabled would mean every project that DOES adopt the
convention has to discover a switch before the protection does anything, which
is the failure mode the owner described — reasoning from a stale checkout
without ever being told.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, ReferenceReposConfig


class TestDefaultsCarryTheRulings:
    def test_it_is_enabled_out_of_the_box(self) -> None:
        assert ReferenceReposConfig().enabled is True

    def test_the_default_root_is_the_convention(self) -> None:
        """`untracked/repos` is the convention being standardised across projects."""
        assert ReferenceReposConfig().roots == ["untracked/repos"]

    def test_nothing_is_excluded_by_default(self) -> None:
        assert ReferenceReposConfig().exclude == []

    def test_the_default_mode_is_block_once(self) -> None:
        """Owner ruling: block once per repo per session, and configurable."""
        assert ReferenceReposConfig().mode == "block_once"

    def test_auto_pull_is_on_by_default(self) -> None:
        """Owner ruling: the daemon pulls when provably safe."""
        assert ReferenceReposConfig().auto_pull is True

    def test_the_cache_ttl_has_a_sane_default(self) -> None:
        assert ReferenceReposConfig().cache_ttl_minutes == 15


class TestModeIsConstrained:
    @pytest.mark.parametrize("mode", ["block_once", "block", "advise", "off"])
    def test_every_documented_mode_is_accepted(self, mode: str) -> None:
        assert ReferenceReposConfig.model_validate({"mode": mode}).mode == mode

    def test_an_unknown_mode_is_rejected(self) -> None:
        """A typo must fail loudly, not degrade to some silent default.

        A mode of `blcok_once` that quietly fell back to `off` would disable the
        protection while the config file claims it is on.
        """
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"mode": "blcok_once"})


class TestRejectingNonsense:
    """Validated through `model_validate`, which is how YAML config really arrives.

    Passing these values as keyword arguments would be rejected statically by
    the type checker before the test could run, and a config file is a dict from
    disk — so the dict form is both the honest path and the one under test.
    """

    def test_an_unknown_key_is_rejected(self) -> None:
        """extra=forbid: a misspelled key is a silent no-op otherwise."""
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"auto_pul": True})

    def test_a_zero_ttl_is_rejected(self) -> None:
        """A zero TTL expires instantly, so every read would be NOT VERIFIED."""
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"cache_ttl_minutes": 0})

    def test_a_negative_ttl_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"cache_ttl_minutes": -5})

    def test_an_absolute_root_is_rejected(self) -> None:
        """Roots are repository-relative, like every other path in this config.

        An absolute root would also let a config point the sweep at `/`, which
        the depth bound limits but should not have to.
        """
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"roots": ["/srv/shared/repos"]})

    def test_a_root_escaping_the_repository_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"roots": ["../elsewhere"]})

    def test_an_empty_root_string_is_rejected(self) -> None:
        """An empty string resolves to the project root itself, not to nothing."""
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"roots": [""]})

    def test_the_repository_root_itself_is_rejected_as_a_root(self) -> None:
        """A root of `.` would govern the project's OWN repository.

        Plans 00178/00179 already own the project repo's freshness, and this
        plan's Non-Goals exclude it explicitly — so the config cannot express it.
        """
        with pytest.raises(ValidationError):
            ReferenceReposConfig.model_validate({"roots": ["."]})


class TestCustomisation:
    def test_several_roots_are_allowed(self) -> None:
        config = ReferenceReposConfig(roots=["untracked/repos", "vendor/upstream"])

        assert config.roots == ["untracked/repos", "vendor/upstream"]

    def test_no_roots_at_all_is_allowed(self) -> None:
        """An explicit empty list is a legitimate way to govern nothing."""
        assert ReferenceReposConfig(roots=[]).roots == []

    def test_exclude_globs_are_carried(self) -> None:
        config = ReferenceReposConfig(exclude=["**/scratch", "**/archive"])

        assert config.exclude == ["**/scratch", "**/archive"]


class TestReachableFromTheRootConfig:
    def test_the_block_exists_on_the_root_config_with_defaults(self) -> None:
        assert Config().reference_repos.mode == "block_once"

    def test_it_can_be_set_from_a_config_document(self) -> None:
        config = Config.model_validate({"reference_repos": {"mode": "advise", "auto_pull": False}})

        assert config.reference_repos.mode == "advise"
        assert config.reference_repos.auto_pull is False
        assert config.reference_repos.roots == ["untracked/repos"]
