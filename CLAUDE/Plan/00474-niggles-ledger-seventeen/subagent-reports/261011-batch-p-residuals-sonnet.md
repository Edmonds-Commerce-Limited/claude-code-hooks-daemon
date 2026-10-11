# Batch P: residuals of N410, N371, N403

Cleared (each bullet marked in NIGGLES.md):

- N410, all five. Handler docstring for the `$V/<tool>` branch; every non-option operand (leading `<` stripped) of a
  variable-led literal tool is judged by content (red 5: run/flag-value/`<`/`<sig`/multi-operand); seven shells added
  to `_SHELL_HEADS` plus `busybox <applet>` read as the applet (red 7); QA.md and `merge_qa_advisor` wording (red 1).
  The `$V/hooks-daemon upgrade` row is pinned as ALLOW, not DENY: the CLI has no `upgrade` subcommand (`upgrade` is the
  skill name; the entry points are `upgrade.sh` and friends), so the premise "it is the governed entry point" does not
  hold; it was already allowed before this batch and still is. Variable-led `upgrade.sh` under `PYTHONPATH` is pinned
  as DENY. Owner to say if the bare word should be denied.
- N371, two of four: byte-parity test (`tests/unit/scripts/test_mkplan_template_parity.py`, green on arrival, a guard);
  fallback advice now "higher of the counter and the highest plan on disk, then add 1" (red 1). CLAUDE.md block is
  generated from the handler text; I did not regenerate it, the coordinator's daemon restart does. Still residual: the
  scan-depth mismatch between `mkplan.bash` and the daemon, and `mkroutine.bash`.
- N403, three of five: `>(`/`<(` targets skipped in `_write_redirects` (red 2); `command [-p] cd` is a move,
  `command -v cd` is not (red 2). The function lives in `utils/git_commit_parsing.py` and the git gates read
  directories through it. Test data written plainly. Still residual: the `$VAR` substitution and group-redirect items.

No file in the N374/N375/N333/N335 scope was touched.

Tests: `tests/unit/utils`, `tests/unit/handlers/pre_tool_use`, `tests/unit/scripts` and the ordinary-command regression
gate: 18378 passed, 1 skipped.
