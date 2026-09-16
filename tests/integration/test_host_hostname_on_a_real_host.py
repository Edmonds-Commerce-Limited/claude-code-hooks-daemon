"""Rung 2 of the host-name ladder, verified against a REAL machine.

Plan 00411. Two of that plan's success criteria were verified live inside this
project's podman container — the explicit hand-off resolves, and an unexported
container renders no segment at all. The third could not be: "on a desktop host
and under LXC, the real hostname shows with no export needed" was covered by
unit tests and deliberately left unticked, because the whole lesson of the
other two was that live behaviour had already surprised the tests once.

Waiting for someone to sit at a desktop is a poor way to close that gap. CI
runs on a GitHub-hosted `ubuntu-latest` runner with no ``container:`` key in
`.github/workflows/qa.yml`, so the job executes directly on the VM — a bare
host as far as :func:`detect_container_runtime` is concerned. That makes every
CI run a live host verification, on real hardware, automatically and for ever,
which is strictly better evidence than one person checking once.

**This test SKIPS inside a container**, which is where it usually runs during
development, so it is genuinely CI that does the verifying. A skip is honest
here: the claim is about hosts, and inside a container there is no host to ask.

What remains unverified after this is narrower than what the criterion started
as: LXC specifically. LXC takes the SAME rung — :func:`socket.gethostname` —
and differs only in that :func:`detect_container_runtime` must return ``"lxc"``
rather than ``None`` for the guard to let that rung answer. So the residual
risk is no longer "does the resolver work off-container", it is "is LXC
correctly recognised", which is a smaller and separate claim.
"""

from __future__ import annotations

import socket

import pytest

from claude_code_hooks_daemon.utils.container_detection import detect_container_runtime
from claude_code_hooks_daemon.utils.host_identity import (
    HOST_HOSTNAME_ENV_VARS,
    HostNameSource,
    resolve_host_name,
)

_runtime = detect_container_runtime()

pytestmark = pytest.mark.skipif(
    _runtime is not None,
    reason=(
        f"runs in a {_runtime} container; rung 2 is about a real host, and there "
        "is no host to ask from in here. CI runs bare on the runner VM and does "
        "verify it."
    ),
)


@pytest.fixture
def no_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear rung 1 so rung 2 is genuinely what answers.

    Without this the test would pass on any machine that happens to export a
    hand-off variable, proving nothing about the rung it names.
    """
    for name in HOST_HOSTNAME_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class TestOnABareHost:
    def test_the_real_hostname_resolves_with_no_export(self, no_handoff: None) -> None:
        """The criterion, stated as an assertion."""
        resolved = resolve_host_name()

        assert resolved is not None, (
            "No host name resolved on a machine that is not in a container. "
            "Rung 2 should have answered with socket.gethostname()."
        )
        # The cleaner strips surrounding whitespace and refuses a name outright
        # rather than editing it, so a resolved name is the machine's name
        # verbatim — no domain trimming to account for here.
        assert resolved.name == socket.gethostname().strip()

    def test_it_is_authoritative_rather_than_inferred(self, no_handoff: None) -> None:
        """An /etc/hosts hint answering here would be the wrong rung winning.

        Rung 3 is a guess whose correctness depends on the host distribution.
        On a real host rung 2 cannot be wrong, so it must be the one that fires
        — and the segment must not carry the inferred marker.
        """
        resolved = resolve_host_name()

        assert resolved is not None
        assert resolved.source is HostNameSource.LOCAL
        assert resolved.inferred is False

    def test_the_hand_off_still_wins_when_present(
        self, monkeypatch: pytest.MonkeyPatch, no_handoff: None
    ) -> None:
        """Rung 1 outranks rung 2 even where rung 2 would have been right.

        The matched pair for the tests above: without it, "rung 2 answers on a
        host" could be true because the ladder had silently stopped consulting
        rung 1 at all.
        """
        monkeypatch.setenv(HOST_HOSTNAME_ENV_VARS[0], "explicit-host-name")

        resolved = resolve_host_name()

        assert resolved is not None
        assert resolved.name == "explicit-host-name"
        assert resolved.source is HostNameSource.ENVIRONMENT
