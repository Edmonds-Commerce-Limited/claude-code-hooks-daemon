# Task 4.7 report

## Finding

The sweep printed remote deletes from its own inventory verdict, not the guard's proof:

- `core/branch_sweep.py` `delete_action`: for a remote-only done branch printed
  `git push <remote> --delete <name>` whenever `proven_by` was a remote-tracking ref.
- `core/branch_cleanup.py` `remote_delete_command`: printed the same line for every deleted or
  cleanable local branch with a tracking ref (report, `--clean`, `--dry-run`, WorktreeRemove
  cleanup, merge cleanup).
  Neither consulted `remote_branch_proof`. The shape that diverges: tracking ref shows a merged tip,
  but the live remote tip has moved (stale tracking ref). The guard refuses it (live-tip check).

## Change

- `remote_delete_command` replaced by `remote_delete_advice(repo, config, default, name)`: runs
  `named_ref_problem` then `prove_remote_merged`; runnable line only when proven, else
  "remote delete of <remote>/<name> is for the owner: <reason>" (advice, not a command).
- New `proven_remote_only(repo, config, inventory)` (reuses `_proven_remote`); the `branch-sweep`
  CLI passes the result as `remote_proven` to `render_report` / `report_json`.
- `delete_action` prints the runnable remote-only line only for names in `remote_proven`
  (default empty, fail closed); otherwise owner-only wording.

## Tests

New `tests/unit/core/test_branch_sweep_remote_delete_lines.py` (real repos with a bare remote;
every printed delete line is fed to `DestructiveGitHandler`): squash-merged remote-only branch gets
an allowed line; stale-tracking branch gets owner wording and no line; mixed case; report without
proof prints none. 4 passed. Existing branch sweep / cleanup / pools / archive-proof / CLI / session
start / stop gate tests pass (separate invocations). QA 6/6 (format lint type_check error_hiding
magic_values semgrep).

Note: the new test was written after the implementation in the same pass, so the red phase was not
run separately; the old behaviour is evidenced by the code paths above.

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/041-branch-sweep-prints-only-remote-deletes-the-guard-allows.md`
