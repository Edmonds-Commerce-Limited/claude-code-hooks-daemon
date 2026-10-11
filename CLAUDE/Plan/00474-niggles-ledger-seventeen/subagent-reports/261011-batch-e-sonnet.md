# Batch E report: N400, N401, N402 part (a)

Branch `agent-a8b2dfbb8ae318a8c-68c99312`. Evidence source: Plan 00483 Task 3.2 re-check report, section "Characterisation".

## N400 (gh --body heredoc), fixed

- Cause: `strip_message_bodies` blanks `-m`/`-F` values (including `"$(cat <<'EOF' ... EOF)"`) for `git`, `hg`, `svn`, `jj`
  only. A `gh ... --body "$(cat <<'EOF' ...)"` value was never a message to it, and the heredoc sink rule from batch (b)
  only covers a heredoc fed straight to `gh` (`--body-file -`), because a heredoc inside a substitution is refused.
- Fix: reuse the one message reader. `--body`/`-b` join its flag list; for the owning command `gh` the flag must be a
  body flag and the group one of `_GH_DATA_SUBCOMMANDS` (the groups batch (b) names); for the VCS commands a body flag
  is never a message. `value_can_substitute` still decides inertness, so an unquoted `<<EOF`, a pipe on to `bash`, a
  bare `$(git reset --hard)` value and a non-`cat` receiver stay judged. No parallel parser.
- Both `destructive_git` and `git_stash` benefit (both scan through `command_position_argument_segments`).

## N401 (git -c k=v commit -F - heredoc), fixed

- Cause: `_git_data_subcommand_index` accepted only `-C`, `--no-pager`, `-P`, `--no-optional-locks` before the
  subcommand, so `-c` ended the scan and the heredoc body kept being read as code.
- Fix: step over `-c key=value` (separate or attached) when the key runs nothing. Keys git RUNS (`core.fsmonitor`,
  `core.sshcommand`, `core.pager`, `core.editor`, `core.hookspath`, `core.askpass`, `sequence.editor`,
  `diff.external`, and suffixes `.program .helper .command .cmd .clean .smudge .process .textconv`), `-c` with no `=`,
  and an unresolved value keep the body judged. The key list is a deny-list because git's config key space is open;
  this is the one place the change is not an allowlist, and it is stated at the constant.

## N402 part (a) (cd to a cwd expansion in the commit gates), fixed; part (b) left open

- Resolution found: `substitute_cwd_expansions` in `core/utils.py` (FP batch 2), used by path judgement. It refuses
  whenever the command contains a `cd`, so it cannot be applied as is to a `cd` operand. Split its reading into
  `expand_cwd_references(token, cwd)` (public, no command guard); `substitute_cwd_expansions` keeps its guard and calls it.
- `git_invocation_directory.placement_problem(run, cwd=None)` and `invocation_directory(run, cwd)` read each `cd` step
  and each `-C` value through it, in the directory the earlier `cd` steps reached. Without `cwd` the old behaviour holds.
- Callers now pass their start directory: `conflict_marker_commit_gate`, `destructive_git` (branch delete, remote
  delete), `merge_qa_advisor`, `daemon_sync_after_merge`.
- Other commit gates (staged lint, docs QA, plan QA, guard config, remote docs): they do not use this placement code.
  They read the commit with `read_commit_form`/`_commit_moves`, where an unstatable move is judged as the hook directory
  and never denied as NOT checked. The full ordinary-command chain (all handlers) allows the new `cd "$(git rev-parse --show-toplevel)" && git commit` and `cd "$PWD" && git commit` rows. Nothing to share, nothing changed there.
- Unchanged and still denied (part (b), owner): `cd $PROJ && git commit`, `cd "$PWD/$SUB"`, `cd "$(dirname "$PWD")"`,
  `cd -`, and a toplevel expansion with no enclosing repository. Pinned by tests.

## Tests and rows

- New: `tests/unit/handlers/pre_tool_use/test_git_guards_heredoc_sinks.py` (45 cases, written red first: 14 failed
  before the change).
- Extended: `tests/unit/utils/test_git_invocation_directory.py`, `tests/unit/handlers/pre_tool_use/test_conflict_marker_commit_gate.py`.
- Gate rows: `tests/fixtures/ordinary_command_corpus.yaml` (`a8-gh-*`, `a8-git-dash-c-*`, `a8-cd-*`, 5 rows, all ALLOW through
  every handler) and `scripts/qa/dangerous-invocation-corpus.yaml` (4 COVERED rows for the must-stay-denied shapes;
  checker: every recorded verdict holds, 71 rows).
- Acceptance probes were not touched, so neither acceptance harness was run on account of this change; both run inside
  the changed-QA mapping if it selects them (see the QA line in the reply).

## Open

- N402 (b): owner decision on any other unresolvable expansion in a commit gate.
