# N328: errexit has no effect under the Bash tool harness (sonnet)

Branch: worktree-n328-errexit-harness. The rulings below were the coordinator's (agent rulings, not the owner's).

## Changes

- `verification_result_gate`: a top-level `set -e` (also inside `{ }` or `( )`) no longer stands the gate down. Errexit only counts when declared inside a heredoc body fed to a fresh interpreter (`bash <<'EOF'`), found as the statements the executable-body view has that the outer view lacks. `bash -c '...'` bodies were already opaque, so they stay accepted. Rule fix, verbose text, warn/block messages and `get_claude_md()` drop `set -euo pipefail` as a remedy and say why, worded as "under the current Claude Code Bash tool". The remedy text is now shared constants (the warn and block messages were verbatim duplicates). New acceptance test: `set -euo pipefail; yamllint --version; git tag --list`.
- `bash_safe_mode`: still accepts the prelude, no new denials. Deny message (verbose and terse), RuleSpec fix line and `get_claude_md()` lead with `&&`, `|| exit 1`, `bash -c 'set -euo pipefail; ...'`; the blind-spots list gained the harness item. The old "sibling stands down when a prelude is present" sentence is replaced by the opposite. Already satisfied before this change (now tested): `&&`-only chains, `bash -c` wrappers, `bash -euo pipefail -c`, `bash <<'EOF'` with the set inside.
- `docs/guides/HANDLER_REFERENCE.md` updated for both handlers; release-notes callout `UNRELEASED/release-notes/002-...`; N328 Status line flipped.

## Decisions made by me

- The repo-root CLAUDE.md rule table (auto-generated on daemon restart) still shows the old fix lines for the two rules; I did not hand-edit it. It refreshes on the next restart.
- `.claude/hooks-daemon.yaml` comments on `bash_safe_mode` left alone (project config, not guidance).
- tests/integration/test_main_moved_branching_survives_errexit.py runs real scripts under errexit and is unaffected.
