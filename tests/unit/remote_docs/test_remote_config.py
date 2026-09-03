"""The ``documentation.remote`` policy block (Plan 00326 Task 3.7).

Two knobs, and both exist to move a judgement from per-file to per-project.

``known_sources`` maps a domain to its licence so the licence review happens
ONCE per source rather than once per capture. Without it every document
records the ``unreviewed`` sentinel and the advisory fires forever, which is
how a warning becomes background noise (D13).

``default_staleness`` is the project's freshness window, so a project that
tracks a fast-moving upstream can say so in one place instead of passing
``--stale-after-days`` on every capture (D6).
"""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    DocumentationConfig,
    DocumentationRemoteConfig,
)


class TestDefaults:
    def test_the_block_exists_without_being_configured(self) -> None:
        assert DocumentationConfig().remote is not None

    def test_the_default_window_matches_the_capture_default(self) -> None:
        """Two defaults that disagree would make captures inconsistent."""
        from claude_code_hooks_daemon.remote_docs.capture import DEFAULT_STALE_AFTER_DAYS

        assert DocumentationRemoteConfig().default_staleness_days == DEFAULT_STALE_AFTER_DAYS

    def test_no_sources_are_known_by_default(self) -> None:
        assert DocumentationRemoteConfig().known_sources == {}


class TestKnownSources:
    def test_a_domain_maps_to_a_licence(self) -> None:
        config = DocumentationRemoteConfig(known_sources={"docs.python.org": "PSF-2.0"})

        assert config.licence_for("docs.python.org") == "PSF-2.0"

    def test_an_unknown_domain_has_no_recorded_licence(self) -> None:
        config = DocumentationRemoteConfig(known_sources={"docs.python.org": "PSF-2.0"})

        assert config.licence_for("example.com") is None

    def test_the_domain_is_matched_case_insensitively(self) -> None:
        """Host names are case-insensitive; a config typo should not silently miss."""
        config = DocumentationRemoteConfig(known_sources={"Docs.Python.ORG": "PSF-2.0"})

        assert config.licence_for("docs.python.org") == "PSF-2.0"

    def test_a_url_can_be_used_directly(self) -> None:
        """Callers hold a URL, not a host; making them parse it invites drift."""
        config = DocumentationRemoteConfig(known_sources={"docs.python.org": "PSF-2.0"})

        assert config.licence_for("https://docs.python.org/3/library/os.html") == "PSF-2.0"

    def test_a_blank_licence_is_rejected_rather_than_recorded(self) -> None:
        """An empty string would satisfy the required field while saying nothing."""
        with pytest.raises(ValidationError):
            DocumentationRemoteConfig(known_sources={"example.com": "  "})


class TestValidation:
    def test_a_non_positive_window_is_rejected(self) -> None:
        """Zero would mark every capture stale the moment it was written."""
        with pytest.raises(ValidationError):
            DocumentationRemoteConfig(default_staleness_days=0)

    def test_an_unknown_key_is_rejected(self) -> None:
        """extra=forbid: a typo must fail loudly, not be silently ignored."""
        with pytest.raises(ValidationError):
            DocumentationRemoteConfig(default_stalenes_days=30)
