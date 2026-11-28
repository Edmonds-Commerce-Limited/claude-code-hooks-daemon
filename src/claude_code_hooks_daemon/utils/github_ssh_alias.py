"""The ssh hosts that name GitHub itself (ledger N772).

An account with several GitHub keys commonly gives each one an ssh config
``Host github.com-<suffix>`` entry whose ``HostName`` is ``github.com``, and clones
with ``git@github.com-<suffix>:owner/repo.git``. The alias is resolved by ssh, so it
reaches GitHub; ``gh -R`` and any host comparison must read it as ``github.com``.
GitHub also documents ``ssh.github.com`` (ssh over port 443) as an address of
``github.com``, so it names ``github.com`` too.

Limit: only the ``github.com-<suffix>`` idiom is recognised. Any other ssh config
alias (``github-work``, ``work``) names whatever its ``HostName`` says, which only
reading ssh config could tell, and this module does not read it. Such a host is
returned as written (lowercased): where it is used as a host gh fails closed on it,
and where it is compared it is not taken for GitHub.

Only ssh-style remote URLs (scp form and ``ssh://``) go through ssh config, so only
callers parsing those forms apply this.
"""

from __future__ import annotations

import re
from typing import Final

GITHUB_HOST: Final[str] = "github.com"

#: GitHub's documented ssh-over-HTTPS-port host, and the one port it is reached on.
GITHUB_SSH_OVER_HTTPS_HOST: Final[str] = "ssh.github.com"
GITHUB_SSH_OVER_HTTPS_PORT: Final[str] = "443"

#: ``github.com-`` followed by a non-empty suffix of letters, digits, ``.``, ``-``, ``_``.
_ALIAS: Final[re.Pattern[str]] = re.compile(r"github\.com-[A-Za-z0-9._-]+")


def resolve_ssh_host_alias(host: str) -> str:
    """``github.com`` for an ssh host that names GitHub, else ``host`` lowercased.

    Host names are case-insensitive and gh lowercases them, so the host is matched
    lowercased. A ``github.com-<suffix>`` alias and ``ssh.github.com`` name GitHub.
    """
    host = host.lower()
    if _ALIAS.fullmatch(host):
        return GITHUB_HOST
    if host == GITHUB_SSH_OVER_HTTPS_HOST:
        return GITHUB_HOST
    return host
