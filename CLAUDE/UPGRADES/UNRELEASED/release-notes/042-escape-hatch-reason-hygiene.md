# Callout: a `MUST_*_BECAUSE` escape hatch is only honoured when it carries a specific reason

**Plan**: 00484
**Audience**: everyone

The `MUST_*_BECAUSE` hatches stay (`MUST_STASH_BECAUSE`, `MUST_SQUASH_BECAUSE`, `MUST_SCAN_ROOT_BECAUSE`, `MUST_SKIP_SAFE_MODE_BECAUSE`, `MUST_EXCEED_COMMENT_SIZE_BECAUSE`, `MUST_EXCEED_PLAN_SIZE_BECAUSE`), but three hygiene gaps are closed through one shared check. `MUST_SKIP_SAFE_MODE_BECAUSE` used to be honoured as a bare word, with no reason at all; it now needs `="reason"` like the other command hatches. `MUST_EXCEED_COMMENT_SIZE_BECAUSE: */` or `: -->` counted as a reason because the closer was the rest of the line; a comment closer alone is now nothing. A placeholder reason (`because`, `needed`, `n/a`, `none`, `tbd`, `explain why`, and similar) is no longer a reason in any of the six.

A hatch that is not honoured never creates a deny of its own: the guard it was meant to bypass simply applies, as if no hatch had been written. A command or file that carried a real reason behaves exactly as before.
