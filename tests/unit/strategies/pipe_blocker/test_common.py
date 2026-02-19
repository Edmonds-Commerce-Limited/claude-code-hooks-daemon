"""Tests for pipe_blocker common constants."""

from claude_code_hooks_daemon.strategies.pipe_blocker.common import (
    UNIVERSAL_WHITELIST_PATTERNS,
)


class TestUniversalWhitelistPatterns:
    """Tests for UNIVERSAL_WHITELIST_PATTERNS constant."""

    def test_is_tuple(self) -> None:
        assert isinstance(UNIVERSAL_WHITELIST_PATTERNS, tuple)

    def test_non_empty(self) -> None:
        assert len(UNIVERSAL_WHITELIST_PATTERNS) > 0

    def test_all_strings(self) -> None:
        for pattern in UNIVERSAL_WHITELIST_PATTERNS:
            assert isinstance(pattern, str)

    def test_contains_grep(self) -> None:
        assert r"^grep\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_rg(self) -> None:
        assert r"^rg\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_awk(self) -> None:
        assert r"^awk\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_sed(self) -> None:
        assert r"^sed\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_jq(self) -> None:
        assert r"^jq\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_cut(self) -> None:
        assert r"^cut\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_sort(self) -> None:
        assert r"^sort\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_uniq(self) -> None:
        assert r"^uniq\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_tr(self) -> None:
        assert r"^tr\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_wc(self) -> None:
        assert r"^wc\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_cat(self) -> None:
        assert r"^cat\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_echo(self) -> None:
        assert r"^echo\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_ls(self) -> None:
        assert r"^ls\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_git_tag(self) -> None:
        assert r"^git\s+tag\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_git_status(self) -> None:
        assert r"^git\s+status\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_git_diff(self) -> None:
        assert r"^git\s+diff\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_date(self) -> None:
        assert r"^date\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_contains_pwd(self) -> None:
        assert r"^pwd\b" in UNIVERSAL_WHITELIST_PATTERNS

    def test_all_patterns_are_regex_strings(self) -> None:
        """All patterns should be valid regex (anchored at start)."""
        import re

        for pattern in UNIVERSAL_WHITELIST_PATTERNS:
            # Should compile without error
            re.compile(pattern, re.IGNORECASE)

    def test_patterns_match_expected_commands(self) -> None:
        """Verify key patterns match their intended commands."""
        import re

        cases = [
            (r"^grep\b", "grep -rn pattern"),
            (r"^ls\b", "ls -la"),
            (r"^cat\b", "cat /etc/passwd"),
            (r"^git\s+tag\b", "git tag -l"),
            (r"^git\s+status\b", "git status --short"),
            (r"^git\s+diff\b", "git diff HEAD"),
        ]
        for pattern, command in cases:
            assert re.search(
                pattern, command, re.IGNORECASE
            ), f"Pattern {pattern!r} should match {command!r}"

    def test_patterns_do_not_match_non_commands(self) -> None:
        """Verify patterns do NOT match non-whitelist commands."""
        import re

        for pattern in UNIVERSAL_WHITELIST_PATTERNS:
            # pytest should not match any whitelist pattern
            assert not re.search(pattern, "pytest", re.IGNORECASE)
            # npm test should not match any whitelist pattern
            assert not re.search(pattern, "npm test", re.IGNORECASE)
