# Issues #64 and #66, step 1: glob base (sonnet-5-5)

Branch `worktree-issue-66-glob-base`. Step 2 (quote-awareness of text operands) is not done here.

## Root cause (confirmed)

`_expand_glob_token` (`utils/secret_file_matching.py`) added `Path.cwd()`, the daemon
process cwd (`/` under the live daemon), as a glob base for every relative token.
`bounded_recursive_glob` (`utils/shell_expansion.py`) refuses a `**` or 2+-wildcard
glob rooted at `/` before checking whether the glob's literal prefix exists. So text such
as `!a/**` or `untracked/scratch/repro/*/data.json` raised TooManyToEnumerateError, and
both guards map that to a deny. The quarantine guard called `find_protected_mention_strict`
with no cwd at all.

## Change

- `_expand_glob_token`: bases are project root plus the hook cwd. The daemon process cwd is gone.
- `find_protected_mention_strict(command, patterns, cwd=None)`; the quarantine guard reads
  `cwd` from the payload and passes it (`_bash_mention` gained a `cwd` parameter).
- `bounded_recursive_glob`: at a root base, if the pattern's leading non-wildcard components
  do not exist (`_literal_prefix_exists`), it yields nothing. Only ENOENT/ENOTDIR/ELOOP prove
  absence; any other error (notably ENAMETOOLONG for a joined path past PATH_MAX) answers
  "exists" so the walk fails closed as before.

## Relaxed paths (all of them)

1. A relative glob is no longer tried against the daemon process cwd. Bash runs in the
   payload cwd, so this base was never where a tool call read files. Consequence: a caller
   with neither a project root nor a hook cwd has no relative base (unit-test shape only; the
   daemon always has a project root and payloads carry `cwd`).
2. A glob at a root base with an absent literal prefix matches nothing instead of raising.
   A prefix-less broad glob (`**`, `*/*`) and a broad glob under an existing prefix
   (`usr/**`) still raise; tests cover both.

## TDD

Tests in `tests/unit/utils/test_glob_base_payload_cwd.py`, all with `monkeypatch.chdir("/")`.
Red output before the fix: `9 failed, 9 passed`, failures
`TooManyToEnumerateError: refusing to walk a broad glob rooted at the filesystem root: //...`
(the `!a/**`, `nothing/**`, `nothing/*/*`, `no-such-dir/*/x/*` root-walk cases, the quarantine
`grep -rn !a/** docs` / `--exclude-dir=nothing/**` / `cat !a/*/*/x` cases, the strict matcher
called directly, and the #66 command through the secret guard). Positive controls that must
stay denied and passed both before and after: an unquoted glob matching a real artefact in
the payload cwd, one reaching an artefact below it via `**`, an unquoted glob matching a
protected default-pattern file in the payload cwd, and one via `conf/*/...`.

## Existing tests changed

Four tests relied on `monkeypatch.chdir(tmp_path)` with no payload cwd (process cwd as base).
They now pass the payload `cwd` (`_hook_input(..., cwd=tmp_path)`): in
`test_quarantine_artefact_read_guard.py`, `test_glob_token_that_expands_to_a_real_detail_artefact_still_matches`,
`test_a_relative_glob_past_path_max_once_joined_denies` and
`test_an_unquoted_glob_past_the_budget_is_a_named_deny`. No assertion loosened. Other tests in
that class that `chdir` and expect ALLOW now pass without a base, so they are weaker than
before; they are left as is.

## Notes for step 2

- The #66 command is still enumerated from the project root and payload cwd (quoted text
  inside a python program); it is only allowed now because the real base has no explosion.
  A quoted glob under a huge real tree would still walk to the 2000-entry cap.
- The strict quarantine path already gates on unquoted glob characters (N238); the secret
  guard's both-edges path has no quote information, as the triage said.
- This session's own shell hit the same class: a `grep -o ".*Error.*"` in a Bash command was
  denied R-SECRET-BASH-MENTION for its quoted `.*Error.*` token. Good regression text for step 2.
