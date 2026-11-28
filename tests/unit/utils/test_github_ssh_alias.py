"""The ssh host alias idiom ``github.com-<suffix>`` names GitHub itself (ledger N772)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.github_ssh_alias import resolve_ssh_host_alias


class TestResolveSshHostAlias:
    @pytest.mark.parametrize(
        "host",
        ["github.com-lts", "github.com-work", "github.com-a.b_c-9", "github.com-X"],
    )
    def test_the_alias_idiom_names_github(self, host: str) -> None:
        assert resolve_ssh_host_alias(host) == "github.com"

    @pytest.mark.parametrize(
        "host",
        [
            "github.com",
            "ghe.example.com",
            "github.com-",
            "github.com-a+b",
            "github.com-a/b",
            "github.com-a:b",
            "github.com-a b",
            "xgithub.com-lts",
            "github.comx-lts",
            "github.org-lts",
            "gitlab.com-lts",
            "",
        ],
    )
    def test_any_other_host_is_unchanged(self, host: str) -> None:
        assert resolve_ssh_host_alias(host) == host
