"""Assembling an upstream issue report that cannot carry the client's material.

This repository's issue tracker is PUBLIC, and a public issue cannot be
retracted by editing or deleting it. A client project filing a daemon defect
therefore bears a permanent cost for anything it discloses, while the cost of
over-redacting is one round trip asking for more detail. The two are not
comparable, and this package is written to that asymmetry (Plan 00403).

The generator, the verification gates and the filing handler all import from
here, so that they cannot drift in what they consider a valid report — a gate
judging a report by a different rule from the one that built it would either
refuse valid reports or pass leaking ones.
"""

from __future__ import annotations

from claude_code_hooks_daemon.issue_report.reproduction import (
    CANNOT_REPRODUCE_SENTINEL,
    SCRATCH_PREFIX,
    ReproductionProblem,
    check_reproduction,
)

__all__ = [
    "CANNOT_REPRODUCE_SENTINEL",
    "SCRATCH_PREFIX",
    "ReproductionProblem",
    "check_reproduction",
]
