# Code Review: handlers/ slice of v3.62.1..HEAD (release gate, v3.63.0)

## Summary

Eight findings, none blocking. The slice is large but overwhelmingly disciplined:
most of the churn is a mechanical acceptance-test migration (declared tool
payloads and `dispatch_as_bash` flags) plus a systematic replacement of raw
`Path.exists()/is_file()/is_dir()` with the new `utils/path_predicates` helpers
that force each call site to state what an unstattable path means. The genuinely
new behaviour is concentrated in three places: `sensitive_content`'s staged-commit
and GitHub-body surfaces, `model_downgrade_recorder` (new handler), and the
`failsafe_cron_blockage_suppressor` cadence backoff. All eight findings live in
that new behaviour or in two new regexes.

Reviewed: 89 files, 3713 insertions, 836 deletions in
`src/claude_code_hooks_daemon/handlers/`.

Issues found: 0 blocker, 5 important, 3 suggestion.

Verification run during review:

| check | result |
| --- | --- |
| `tests/unit/handlers` | 6093 passed, 1 skipped, 1 xfailed |
| prose-match, EACCES-static, stop-shadowing, pipe-blocker integration guards | 45 passed |
| added lines containing TODO/FIXME/HACK/breakpoint/print | 0 |
| language-name `if`/`elif` chains added | 0 |

Probe scripts written for this review, kept as evidence:

- `untracked/scratch/probe_commit_all_misparse.py` (finding 2, reproduces)
- `untracked/scratch/probe_destructive_git_patterns.py` (finding 4, reproduces)
- `untracked/scratch/probe_haystack_cache_id.py` (finding 1, mechanism reproduces, trigger does not)
- `untracked/scratch/probe_id_reuse.py` (finding 1, negative result)
- `untracked/scratch/probe_gh_body_file_unreadable.py` (finding 5, cannot run as root)
- `untracked/scratch/probe_tail_scan_cost.py` (measurement, no finding)

## Critical Issues

None. No security hole, no data-corruption path, no missing test for a behaviour
change, and no handler priority outside its band. `Priority.MODEL_DOWNGRADE_RECORDER
= 33` sits with its PostToolUse siblings (`command_hints` 29, `recovery_cron_advisor`
30, `goal_injection` 31, `budget_exhaustion_detector` 32) inside the 25-35 quality
band.

## Important Issues

### 1. `sensitive_content` caches per-dispatch state under `id(hook_input)` (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:316-407`

**Problem:** `_haystacks_for` memoises the computed haystacks on the handler
instance and keys the entry on `id(hook_input)`. `id()` is unique only among
LIVE objects. The daemon builds each event's dict in `controller.dispatch`
(`event.hook_input.model_dump(by_alias=False)`) and drops it when the dispatch
ends, so a later dict allocated at that freed address compares equal to the
cached key. The handler then answers the NEW event from the PREVIOUS event's
text.

Two aggravating factors. The daemon dispatches on a thread pool
(`daemon/server.py`, `run_in_executor(None, self.controller.dispatch, ...)`), so
one handler instance really is shared across concurrently allocating events.
And `budget_exhaustion_detector` removed its own `self`-stashed per-event cache
in this same release for the neighbouring reason, documenting it as a
cross-session leak, so the two handlers now disagree about whether this is safe.

**Evidence:** `probe_haystack_cache_id.py`. Part 2 sets the cache key to the
next event's id, exactly what an address collision produces, and a clean
`git tag -m 'ordinary release note' v2` is then denied on the previous event's
matched pattern.

Part 1 is a negative result and is why this is not a blocker: across 50,000
real-shaped `model_dump()` dispatches the outer dict never landed on the freed
address, because the nested `tool_input` dict takes the slot first. A bare
one-level dict reuses its address 100% of the time, so the margin here is an
allocation-order accident, not a guarantee. CPython promises nothing about `id`
uniqueness over time.

**Why it matters:** the failure is silent and bidirectional. In one direction a
clean commit is denied naming another call's pattern; in the other a blocked
term reaches a commit or a GitHub comment unexamined, which is the outcome the
handler exists to prevent.

**Suggested fix:** keep the cache, but make the key content-derived rather than
address-derived. `(session_id, tool_name, command-or-file_path)` is already in
hand at every branch of `_compute_haystacks` and costs one tuple compare. If a
stronger guarantee is wanted, clear the cache from `commit_side_effects` the way
`command_hints` and `recovery_cron_advisor` now bracket their journals. Add a
unit test: no test currently touches `_cached_input_id`.

---

### 2. `_is_git_commit` reads a short flag out of a quoted commit message (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:203-228`

**Problem:** the function tokenises with a bare `command.split()`, so quoting is
invisible to it. Any whitespace-delimited word inside a quoted message that
starts with one dash and contains an `a` is read as the all-flag, and
`_staged_content_haystacks` then diffs against `HEAD` (the whole dirty working
tree) instead of `--cached` (what the commit would actually record).

**Evidence:** `probe_commit_all_misparse.py`.

```
WRONG commits_all=True  expected=False diff_target=HEAD  git commit -m 'fix the -a flag handling'
WRONG commits_all=True  expected=False diff_target=HEAD  git commit -m "document -a and -am shorthands"
OK    commits_all=False expected=False diff_target=--cached  git commit -m 'plain message'
OK    commits_all=True  expected=True  diff_target=HEAD  git commit -am 'genuine all'
```

**Why it matters:** an UNSTAGED file can deny a commit that never included it,
and the deny reason names a path the author did not stage and cannot find in the
index. A repository that documents command-line flags in its own commit messages
hits this readily. The direction is over-blocking, which is the safe side, but
the message is actively misleading.

**Suggested fix:** tokenise with `shlex.split` (falling back to `split()` on
`ValueError` for an unbalanced quote), or scan only the tokens before the first
`-m`/`--message` value. Add a regression test for a message quoting a short
flag.

---

### 3. `_added_lines_by_path` does not unquote git's quoted paths (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:230-249`, consumed at `:501-510`

**Problem:** `core.quotePath` defaults to true, so git emits a C-quoted, still
`b/`-prefixed header for any path with a non-ASCII character, a quote, a
backslash or a tab. `removeprefix("b/")` cannot strip a prefix that sits inside
the opening quote, so the map key keeps both the quote and the `b/`.

**Evidence:** reproduced against real git in a throwaway repository.

```
+++ "b/caf\303\251.md"
parsed key: '"b/caf\\303\\251.md"'
```

**Why it matters:** the key becomes `repo_root / relpath` at line 507, so both
`self._is_excluded(abs_path)` and `self._is_secret_list_itself(abs_path)`
silently stop matching. A project that excluded a fixture tree via
`daemon.exclude_paths` has that exclusion quietly bypassed for exactly those
files, and the deny reason cites `staged content of "b/caf\303\251.md"`. The
added lines are still scanned, so this is not a detection gap, but it is an
allowlist that stops working on a file-name property nobody would connect to it.

**Suggested fix:** strip a surrounding double quote and decode the C escapes
before `removeprefix`, or take the paths from
`git diff --name-only -z --diff-filter=ACM` (NUL-delimited, never quoted) and
key the added lines off that list. Cover a non-ASCII staged path in the test.

---

### 4. The new `update-ref` pattern spans command separators, unlike its sibling (Confidence: 85%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:109-119`

**Problem:** the force-push pattern immediately above it deliberately confines
itself to one segment with `[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?`, and the module
comment explains why. The new plumbing-branch-delete pattern uses a bare `.*`
instead, so it happily matches across `;` and `&&` and judges one statement by
another statement's text.

**Evidence:** `probe_destructive_git_patterns.py`. The two genuine destructive
shapes and the two near-miss allows all behave correctly; the two cross-separator
cases are denied when they should not be.

```
WRONG denied=True expected=False  git update-ref refs/heads/backup HEAD; echo <delete-flag> refs/heads/backup
WRONG denied=True expected=False  git update-ref refs/heads/backup HEAD && printf -- '<delete-flag> refs/heads/x'
```

(the probe assembles the real flag text from fragments, because writing it
literally is denied by this very handler)

**Why it matters:** over-blocking again, so nothing is destroyed, but a benign
ref-create chained with unrelated text is denied under a rule the command does
not match, and the author has no way to see why. The inconsistency with the
sibling pattern six lines up is the part that will confuse the next reader.

**Suggested fix:** replace `.*` with `[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?`, which
is the convention already established in this file, and add the two probe cases
as regression tests.

---

### 5. A stat-able but unreadable `--body-file` raises out of `matches()` (Confidence: 75%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:452-478`

**Problem:** `path_is_file(path, unreadable_means=False)` answers False only when
the STAT fails. A file whose own mode denies read stats fine, so control reaches
`path.stat().st_size` at line 472 and `path.read_bytes()` at line 475, either of
which can raise `PermissionError`; the same two lines race a file that is
unlinked between the check and the read.

**Why it matters:** `utils/path_predicates`'s own module docstring states the
consequence precisely: the chain catching the raise does not rescue it. With the
client-default `strict_mode: false` the guard silently stops applying for that
command, which drops the inline `--body` haystack too, because
`_compute_haystacks` never returns. With `strict_mode: true` it is a spurious
DENY on legitimate work.

**Evidence:** `probe_gh_body_file_unreadable.py` sets up the case but reports
SKIPPED in this container, which runs as root, so mode 000 does not deny a read.
The finding rests on reading the code and on the helper's own documented
contract, not on an observed failure.

**Suggested fix:** wrap the `stat`/`read_bytes` pair in `try/except OSError`,
log at debug and skip that one body file, matching how `_staged_content_haystacks`
already degrades on a non-zero `git diff` return code.

## Suggestions

- **`_staged_content_haystacks` bounds after materialising the whole diff**
  (`sensitive_content.py:495-501`). `MAX_STAGED_FILE_BYTES` and
  `MAX_STAGED_TOTAL_BYTES` are applied per entry of the already-built map, so
  `run_git` and `_added_lines_by_path` first hold the entire staged diff and a
  full copy of its added lines in memory. The bounds are well chosen and well
  argued; they just do not bound the peak. Passing the total budget into the
  parser, or asking git for `--numstat` first and skipping oversized paths before
  reading their content, would make the constant mean what its comment says.

- **`tdd_enforcement._map_layout_mirror_paths` anchors on `Path.cwd()`**
  (`tdd_enforcement.py:635`) when the source path's first segment is the source
  dir. In a long-running daemon `cwd` is wherever the process started, not the
  project. It is unreachable for the absolute paths R-ABSOLUTE-PATH-REQUIRED
  guarantees, and two pre-existing methods in the same file already do this, so
  it is consistent rather than novel. Worth retiring all three together rather
  than in this release.

- **`suggest_statusline` recommends `refreshInterval: 1`, down from 10**
  (`suggest_statusline.py:30`). Deliberate, documented against a ~39 ms cached
  render, pinned by `test_suggest_statusline.py:150` and by
  `test_install_version_fallback_settings.py`, and adopted in this repo's own
  `.claude/settings.json`. It is still a tenfold increase in a per-session
  recurring subprocess that every client install is advised to adopt, so it
  belongs in the release notes rather than only in a code comment.

## Positive Observations

- **`utils/path_predicates` is the right shape for the problem.** Making
  `unreadable_means` keyword-only with no default forces each of the ~73 call
  sites to state its own answer, and the diff shows genuinely different answers
  chosen for genuinely different reasons: `False` in `comment_size` because the
  naive fallback there biases toward a DENY, `True` in `write_clobber_guard`
  because `False` would invert the guard, `None` in `plan_qa_edit` because three
  downstream checks read the field three different ways. Backed by
  `test_unstattable_caller_paths.py` and a static check
  (`test_eacces_safe_predicates_static_check.py`), with the deliberate exceptions
  marked `eacces-safe-exempt` and each one justified in place.

- **`budget_exhaustion_detector` removed a `self`-stashed per-event cache** and
  documented the concurrency reasoning (F10). Its two new exclusions are
  structural rather than keyword lists: classify a Bash command by whether every
  pipeline stage is a content-passthrough verb, and strip spans that parse as
  this handler's own ledger record shape. The second survives `jq`
  pretty-printing, which a per-line or substring check would not.

- **`model_downgrade_recorder` inverts the attribution problem correctly.**
  Arming on a positively recorded machine action means a human's own model choice
  needs no recognition at all, which retires the manual-marker mirror and its
  hand-synchronised time window in `downgrade_state.py`. The signal write dedupes
  on content so a downgraded session does not churn the file's mtime, and the
  tail scan measures 1.12 ms per tool call against a 19.6 MiB transcript
  (`probe_tail_scan_cost.py`), so shipping it enabled costs essentially nothing.

- **`harness_cannot_produce` is used as an argument, not a label.** Each one
  names what the harness lacks, what converting it would require, who the
  decision belongs to, and which unit test covers the gap meanwhile. The
  `sensitive_content` secret-word-list entries are the strongest case: a
  dispatched payload would have to embed a live blocked term in tracked source,
  and the reason says so and rules the conversion out permanently.

- **`_declares_human_blocked` reasons about its own failure class.** Anchoring
  the sentinel to the declaration position, and excluding prose patterns matched
  inside quoted spans, both come with the concrete incident that motivated them
  and with an explicit contrast against `security_antipattern` and
  `sensitive_content`, which refuse the same quoted-span exemption because there
  quoted text can still execute.

- **Test coverage tracks the behaviour changes.** Every handler with a logic
  change in this range has a test file touched in the same range, or is covered
  by `test_unstattable_caller_paths.py`. The only gaps found are the three new
  cases in findings 1, 2 and 3.

## Verdict

⚠️ APPROVE WITH FOLLOW-UPS - no critical issues; ship v3.63.0 and file findings 1
through 5 as plan tasks.
