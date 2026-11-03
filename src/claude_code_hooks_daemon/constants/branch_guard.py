"""Wording shared by every branch-limit deny (Plan 00558 DESIGN section 12).

One constant so the WIP-cap, dormancy, Stop-guard, force-removal and
evacuation denials, and their handler guidance, cannot drift apart.
"""

from typing import Final

BRANCH_LIMIT_PRINCIPLE: Final[str] = (
    "The limit exists so work FINISHES, never so it disappears. "
    "Finish a branch (merge it), park it with a reason, or delete it only when "
    "the guard proves nothing is lost. Work that serves another lane goes on "
    "that lane's branch, not a new one. A patch or copy saved under an ignored "
    "or untracked directory is lost work, not compliance. If the limit seems to "
    "force a choice between losing work and exceeding it, stop and ask a human."
)
