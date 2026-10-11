# Batch L: scope of the gh -b/--body blanking, and N410

**Cause of the red test**: confirmed. `strip_message_bodies` blanked `-b`/`--body` for any `gh`
whose first word was in `_GH_DATA_SUBCOMMANDS` (`pr`, `issue`, `release`, `gist`, `api`). That set
was written for the heredoc-sink rule (which commands read a heredoc as data) and was reused for a
different question (is the value prose). `gh api --body` is a request-body field, not prose.

**Scope chosen** (`_GH_BODY_PROSE_ACTIONS` in `utils/shell_segmentation.py`, keyed by the verb
after the group, which `_SegmentTracker` now exposes as `action`):

- `gh issue create|comment|edit`
- `gh pr create|comment|edit|review|merge`

Checked against `gh <cmd> --help` (gh is installed): each of these has `-b, --body`.
`gh release create|edit` and `gh gist create|edit` have NO `-b/--body` (release uses `--notes`),
so they are out of scope; the brief listed release, but there is no body flag to blank.
`gh pr merge -b` is the merge commit's body, the same prose as `git commit -m`, which is already
blanked, so it is in. `gh api`, `gh alias`, `gh issue list`, `gh pr view` keep their arguments.
The wider `_GH_DATA_SUBCOMMANDS` stays for the heredoc-sink rule only.

Note `command_position.py` has its own `_narrow_gh_prose` (N241) that blanks `--title/--body/ --notes` for `gh pr|issue|release` independently; not touched, so `command_position_view` still
blanks `gh release create --body`. Tests for those verbs therefore target `strip_message_bodies`.

**Tests**: `TestGhBodyScope` in `tests/unit/utils/test_shell_segmentation_inert_spans.py` (each
in-scope verb with `--body` and `-b`, attached `--body=`, seven out-of-scope shapes, and a chain
where a `gh api` follows a `gh issue comment`); two cases added in `test_command_position.py`.

**N410 trigger** (recorded in NIGGLES.md, Status Open, not fixed): the denial needs a steering
variable (`PYTHONPATH` matches `PYTHON*`) plus a variable program word (`$V/black`, `$V/ruff`,
`$V/mypy`) whose first operand is not a readable file (`src`, `check`). Then
`_variable_program_is_upgrade` -> `_script_run_is_upgrade` -> "cannot tell", which counts as the
upgrade when steered. `$V/python -m pytest` is allowed; literal tool paths are allowed; without
`PYTHONPATH` the variable forms are allowed. The V assignment alone is not the trigger. Pinned by
`TestVariableToolUnderSteeringIsPinned` (asserts today's deny). My own first probe heredoc and a
fix-up script were denied by the same rule while this was being worked on.
