# Callout: stricter config values, a stricter long-running classifier, and safer branch housekeeping

**Plan**: 00618
**Audience**: client projects

These are the non-blocking findings of the release code review. Every change makes a guard deny at least as much as before. Two config values that used to be accepted now fail validation.

**Config validation, may need a change to your `hooks-daemon.yaml`.**

- `omit_permission_surface` must be a real YAML boolean. A quoted or numeric value (`"true"`, `"yes"`, `1`) used to pass validation and then be read as off. It is now rejected, so write `true` or `false` unquoted.
- `ownership_text` may not contain a carriage return, just as it already could not contain a newline.

**Long-running command guard (ships disabled).** It now judges each statement of a `;` list on its own, so a trailing `&` no longer exempts the whole list. It also catches `tail -f`, `sleep infinity`, a long sleep inside `bash -c` or a subshell, and a command behind a leading redirect. `(sleep 100)` and `sleep 100 & wait` move from an advisory to a deny. The background command its deny message offers is no longer cut short, and a bad regex in its policy is logged and no longer drops the valid slow patterns.

**Branch housekeeping.**

- A park record that cannot be parsed is logged and read as "not parked". Before, it made several guards fail open.
- `branch-sweep --clean --apply` re-checks a worktree for unsaved work just before it removes it.
- A park record is cleared only when the delete really happened.
- The post-merge and worktree-remove hooks no longer contact the remote. They print owner-only wording for the remote delete, and `branch-sweep --remote` still does the proven delete.
- `branch-park` puts the branch back when its record cannot be written.
- `branch-sweep --json` gives park-carried branches their `action`.
- The dry-run names the evidence tier behind each delete.
- SessionStart states the open-work cap once.

**Other fixes.**

- The plan-number guard waits at most 2 s for `.git/config.lock`, which keeps it inside its deadline.
- A relay repair cannot start once the daemon has begun stopping.
- The QA scope walk fails on a fatal git error instead of reading it as "not a repository".
- A failed `worktree add` never deletes a directory git still lists.
- `record-venv-tracking` refuses `--tracked-sha` or `--last-release-tag` without `--tracked-ref`.
- An unparsable version-check TTL falls back to the default and no longer drops the branch-install advisory.
- A failed events-dir write leaves no temp file.

**Known limit.** A per-language `lint_on_edit` timeout above about 15 s (for example `timeouts: PHP: 30`) is still cut short by the 20 s PostToolUse chain deadline. That is unchanged in this release.
