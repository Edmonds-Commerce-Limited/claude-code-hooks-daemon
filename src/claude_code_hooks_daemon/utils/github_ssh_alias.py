"""The ssh host alias idiom that names GitHub itself (ledger N772).

An account with several GitHub keys commonly gives each one an ssh config
``Host github.com-<suffix>`` entry whose ``HostName`` is ``github.com``, and clones
with ``git@github.com-<suffix>:owner/repo.git``. The alias is resolved by ssh, so it
reaches GitHub; ``gh -R`` and any host comparison must read it as ``github.com``.

Only ssh-style remote URLs (scp form and ``ssh://``) go through ssh config, so only
callers parsing those forms apply this. Any other host is returned unchanged.
"""

from __future__ import annotations

import re
from typing import Final

GITHUB_HOST: Final[str] = "github.com"

#: ``github.com-`` followed by a non-empty suffix of letters, digits, ``.``, ``-``, ``_``.
_ALIAS: Final[re.Pattern[str]] = re.compile(r"github\.com-[A-Za-z0-9._-]+")


def resolve_ssh_host_alias(host: str) -> str:
    """``github.com`` for a ``github.com-<suffix>`` ssh alias, else ``host`` unchanged."""
    if _ALIAS.fullmatch(host):
        return GITHUB_HOST
    return host
