"""Plan 00627 Task 5.2: the scratch report is printed directly after the branch sweep.

Both handlers sit at priority 56; the chain breaks the tie by name
(``core/chain.py``: slow sweeps last, then priority, then name), and
``git_upstream_checker`` at 56 carries ``SLOW_SWEEP`` so it sorts after both.
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler
from claude_code_hooks_daemon.handlers.session_start.git_upstream_checker import (
    GitUpstreamCheckerHandler,
)
from claude_code_hooks_daemon.handlers.session_start.scratch_sweep import ScratchSweepHandler


def test_scratch_sweep_directly_after_branch_sweep() -> None:
    chain = HandlerChain()
    for handler in (ScratchSweepHandler(), GitUpstreamCheckerHandler(), BranchSweepHandler()):
        chain.add(handler)
    names = [handler.name for handler in chain.handlers]
    assert names.index(ScratchSweepHandler().name) == names.index(BranchSweepHandler().name) + 1


def test_no_other_handler_shares_the_slot_unordered() -> None:
    assert Priority.SCRATCH_SWEEP == Priority.BRANCH_SWEEP
    assert BranchSweepHandler().name < ScratchSweepHandler().name
