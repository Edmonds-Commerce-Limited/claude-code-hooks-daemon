"""Tests for the shared markdown link-target extractor.

Plan 00419 Task 1.4. Both QA subsystems now need the same primitive — docs QA
to resolve pointers, plan QA to resolve plan links — so it lives in one place
rather than being copied into the second caller.
"""

from claude_code_hooks_daemon.utils.markdown_links import extract_link_targets


class TestExtractLinkTargets:
    def test_extracts_every_plain_link_target(self) -> None:
        text = "See [a](docs/Guide.md) and [b](../CLAUDE/Foo.md).\n"
        assert extract_link_targets(text) == ["docs/Guide.md", "../CLAUDE/Foo.md"]

    def test_ignores_targets_inside_a_fenced_block(self) -> None:
        text = "[keep](Bar.md)\n\n```\n[drop](Fenced.md)\n```\n"
        assert extract_link_targets(text) == ["Bar.md"]

    def test_a_backticked_path_is_not_a_link(self) -> None:
        assert extract_link_targets("the `src/foo.py` module\n") == []

    def test_prose_with_no_links_yields_nothing(self) -> None:
        assert extract_link_targets("just prose, no links here") == []

    def test_a_titled_link_yields_only_the_target(self) -> None:
        assert extract_link_targets('[a](docs/Guide.md "Title")') == ["docs/Guide.md"]
