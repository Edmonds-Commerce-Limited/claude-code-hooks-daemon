# Routine 00002 delta run 2026-001 — check `D-RULE`

**Check**: `D-RULE` — changed rules. A deny that became an allow, an exemption
widened, a severity lowered, a handler default flipped to disabled. The reason,
per change.

**Interval**: `v3.63.0..v3.64.0` (432 commits, 907 files).
**Repository**: `/workspace/.claude/worktrees/agent-a4ca40bc85c242e97-a423b26c`
**Answerable**: yes. The diff was produced and read; nothing was skipped for
want of a tool or a path.

**Result**: 1 new finding, 5 reviewed-and-accepted changes, 4 explicit
non-findings.

**Boundary respected**: nothing here overlaps
`scripts/qa/security-downgrade-inventory.yaml`, whose seven rows are all
`fetch-piped-to-shell` / `suppressed-fetch` / `unvalidated-url-expansion` /
`security-downgrade-flag` on the install and upgrade path. `scripts/upgrade.sh`
changed substantially in this interval (+249) but added no new row of those
kinds.

---

## N1 — a token-start anchor turned a deny into an allow for every quoted force flag

### Citation

`src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:77-80`
(identical at `v3.64.0` and at HEAD):

```python
_GIT_PUSH_FORCE_PATTERN = (
    rf"{_GIT_INVOCATION}push\b[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
    r"(?:(?<!\S)--force(?:-with-lease)?\b"
    r"|(?<!\S)-(?!-)[A-Za-z0-9]*f[A-Za-z0-9]*\b"
    r"|(?<!\S)\+\S)"
)
```

At `v3.63.0` the same three alternatives read:

```python
    r"(?:(?:--force(?:-with-lease)?|-f)\b|(?<!\S)\+\S)"
```

### What it allows

Measured by compiling both patterns and running them over the same inputs
(`untracked/scratch/probe2.py`, `untracked/scratch/probe3.py`) — not inferred
from reading:

| command | v3.63.0 | v3.64.0 |
| --- | --- | --- |
| `git push origin main --force` | DENY | DENY |
| `git push origin main "--force"` | DENY | **ALLOW** |
| `git push origin main '--force'` | DENY | **ALLOW** |
| `git push origin main \--force` | DENY | **ALLOW** |
| `git push "-f" origin main` | DENY | **ALLOW** |
| `git push '-f' origin main` | DENY | **ALLOW** |
| `git push origin main "--force-with-lease"` | DENY | **ALLOW** |
| `git push origin feature/lane-f-adoption` | DENY | ALLOW (the intended fix) |
| `git push -uf origin main` | ALLOW | DENY (the intended gain) |

Every quoted row above is a real force push. Bash performs quote removal before
argv, so `"--force"` reaches git as `--force`. Nothing strips quoting before the
pattern runs: `matches()` reads through `get_bash_command`
(`src/claude_code_hooks_daemon/core/utils.py:125-148`), which normalises line
continuations and does nothing else, and `_scan_target` blanks only
quoted-heredoc bodies and inert `-m`/`-F` message values.

### Provenance

The change came from GitHub issue #37 via Plan 00382. Release note
`CLAUDE/UPGRADES/v3/v3.63.0-to-v3.64.0/release-notes/34-a-branch-named-f-is-not-a-force-push.md`
documents both the false positive it fixed and the `-uf` false negative it
closed, and says nothing about quoting. So the deny-to-allow half of the change
is undocumented and, as far as this review can tell, unnoticed.

### The class

**A token-start anchor (`(?<!\S)`, `(?<=^|\s)`) added to a flag literal in a
pattern that is matched against a command string still carrying shell quoting.**

The anchor asks "does this flag begin a whitespace-delimited word". The string it
asks the question of is pre-quote-removal, so a double quote, a single quote and
a leading backslash all defeat it while changing nothing about what the shell
runs.

Membership test, decidable by the next reader without asking: does the pattern
require the flag to START a token, **and** has its scan target not been through a
quote-normalising pass? Both true = a member.

### The class is older than the interval, and the interval generalised it

`(?<!\S)\+\S` has carried the anchor since Plan 00205. A refspec force push with
the plus sign inside double quotes was therefore already an allow at `v3.63.0` —
measured, both versions False. v3.64.0 did not invent the blind spot; it extended
a pre-existing one from one alternative to all three, explicitly and in a comment
("which is the rule the `+`-refspec marker has always followed").

### Asymmetry inside the same handler

At `v3.64.0` no other rule in `destructive_git.py` carries the anchor:

```
89:  rf"{_GIT_INVOCATION}reset\s+.*--hard\b"
93:  rf"{_GIT_INVOCATION}clean\s+.*-[a-z]*f"
130: rf"{_GIT_INVOCATION}branch\s+.*(?-i:-D)\b"
158: rf"{_GIT_INVOCATION}commit\s+.*--amend\b"
```

So the quoted spellings of those four are still denied (measured). One handler
now returns opposite verdicts on the same evasion depending on which rule is
asked. That is the `AsymmetricSiblingProtection` shape, and
`scripts/qa/check_declared_invariant_pairs.py` does not declare this pair.

### It has already spread past the interval

At HEAD (post-`v3.64.0`), `destructive_git.py:174` and `:179-180` —
`R-GIT-CHECKOUT-FORCE` and `R-GIT-SWITCH-FORCE`, both added after the tag — were
written with the same anchor and carry the same hole from birth. Neither rule
exists at `v3.63.0` or `v3.64.0`, so they are outside this interval, but they are
the evidence that the shape propagates by copying.

### Why the test suite does not catch it

The tests added with the change assert exactly the two things the change was
FOR: the `-f-` branch-name false positive is gone, and `-uf` is now denied. The
two new acceptance tests are the grouped-short-flag deny and the prose-in-a-
message allow. Quoting was never a test axis, because under the old unanchored
pattern it was irrelevant — the regression sits in a dimension no test varies.

`scripts/qa/dangerous-invocation-corpus.yaml` does not cover it either: its
force-adjacent rows are `worktree-checkout-force`, `history-filter-branch`,
`control-clean-force`, `ref-push-delete` and `ref-tag-delete`, none of which is a
quoted spelling of a guarded flag.

### Detector hypothesis

**Rejected form (reported as noisy, not clean):** a code-reading rule over
`handlers/**` asserting that every `(?<!\S)` immediately preceding a `-` literal
sits on a quote-normalised scan target. No quote-normalising helper exists today,
so this rule fires on every current site — it would be suppressed inside a
release, which is the failure mode the corpus category's own page warns about.

**Preferred form:** extend the existing corpus harness,
`scripts/qa/check_dangerous_invocation_corpus.py` +
`scripts/qa/dangerous-invocation-corpus.yaml`. Add one row per guarded flag
crossed with the five spellings (bare, double-quoted, single-quoted,
backslash-escaped, clustered), each driven through the real chain and each
recording a measured verdict. Cost is list-writing, which is exactly this
category's declared weakness ("as good as someone's imagination") — but every row
is a fact rather than an opinion, and the false-positive rate is near zero.

**Structural fix (separate from the Defence):** a `strip_shell_quoting` pass in
`utils/shell_segmentation.py`, applied to the scan target. It must UNWRAP quoted
spans, not blank them — Plan 00407 N12 established that blanking every quoted
literal hides an interpreter invocation whose quoted argument IS a command, and
that correction must not be undone.

### Confidence

**High** that the regression is real and reachable: measured on both compiled
patterns, and the absence of any quote-normalising step in the path from
`get_bash_command` to `search()` was read end to end.

**Medium** on the remedy. Whether to unquote the scan target, or to drop the
anchors and re-solve issue #37 another way (e.g. requiring a preceding
whitespace-or-quote rather than whitespace-only), is a design call for the owner.
The quickest correct-looking edit — changing `(?<!\S)` to `(?<![A-Za-z0-9_/.-])`
— would restore the quoted spellings AND keep `lane-f-adoption` allowed, but it
has not been measured here and should not be applied on that basis.

---

## Reviewed, with the reason, and NOT reported as findings

### R1 — `strip_inert_spans` newly applied to two handlers' scan targets

`destructive_git.py::_scan_target` and `daemon_location_guard.py::matches`. A
genuine exemption widening: `-m`/`-F` values and quoted-heredoc bodies are now
blanked before those handlers' patterns run.

**Reason**: Plan 00377 N7 — a commit message describing a newly added `--force`
flag was denied as a force push; and Plan 00407 N3 — an agent writing a report
about that defect was denied for naming the daemon directory in a heredoc.

**Gated three ways** (`utils/shell_segmentation.py::strip_message_bodies`):
the binary must be one of `git`/`hg`/`svn`/`jj`; for git the subcommand must be
in the allowlist (commit, tag, merge, notes, stash); and the value must not be
able to substitute. Plan 00407 N7's `git checkout -m` bypass — where `-m` selects
merge-conflict style and takes no value, so the `--` that makes a checkout
destructive was blanked as though it were commit prose — is explicitly closed by
the subcommand allowlist.

**One boundary worth writing down**: `_MESSAGE_TAKING_SUBCOMMANDS` has a `git`
key only. For `hg`, `svn` and `jj` the code reads

```python
allowed = _MESSAGE_TAKING_SUBCOMMANDS.get(binary)
if allowed is not None and _segment_subcommand(...) not in allowed:
    return match.group(0)
```

so `allowed is None` skips the subcommand check entirely and ANY subcommand's
`-m`/`-F`/`--file` value is blanked for those three binaries. No destructive rule
targets them today, so it is latent rather than live — but it is the same shape
that bit `git checkout -m`, and nothing defends it.

### R2 — `markdown_organization`: an existing `.md` is never a location violation

A new early return: `if path_is_file(self._candidate_on_disk(file_path),
unreadable_means=False): return False`.

**Reason**: the rule is about where NEW markdown lands; editing or rewriting a
file in place moves nothing. An unstattable path reads as absent, so the location
is still judged — fail closed.

**Adds no route.** A Bash redirect into a disallowed path already bypassed this
handler entirely (it keys on `Write`/`Edit`), so "create then write" was already
open.

Same handler, same release: a declared `projects:` entry is now consulted FIRST
and wins outright over the dependency inference (Plan 00365 owner ruling), and
`extra_allowed_markdown_paths` patterns are now tried against the
repository-relative spelling as well as the sub-project-relative one — an
additive rescue, so a widening, with the reason that a config author anchoring at
`^vendor/org/pkg/` is naming the path as they see it.

### R3 — `tdd_enforcement` searches `Tests/` as well as `tests/`

Strictly additive: the gate blocks when NO candidate exists, so a longer search
list can only remove a false block, never create one. Declared locations
(`test_path_map`, `layout.test_dirs`) get no casing variant — the project typed
that directory, so there is nothing to guess.

### R4 — `daemon_restart_verifier` removed from the shared library

Deleted from `handlers/pre_tool_use/`, removed from `HandlerKey`, removed from
`_STRICT_ONLY_HANDLERS`, and added to `RETIRED_HANDLERS` with a full explanation.
Re-homed as a project handler in `.claude/project-handlers/pre_tool_use/`.

**Reason**: its `matches()` was gated on `is_hooks_daemon_repo`, so it was inert
in every client install. Advisory-only in the first place (`terminal=False`,
`Decision.ALLOW`). No protection was lost anywhere.

### R5 — two new gates ship with their enforcing key defaulting FALSE

`plan_close_approval` (gated on `plan_workflow.close_requires_human_approval`,
default `false`) and `merge_to_main_approval` (gated on
`worktree.merge_to_main_requires_human_approval`, default false). Both handlers
are `enabled: true` in the shipped config but inert until the key is turned on.

This is new enforcement offered opt-in, not a relaxation — but it is recorded
here because "a handler default" is exactly what D-RULE watches, and a reader
scanning the config would see `enabled: true` and conclude the gate is live.

---

## Direction of travel

Most of the interval tightens, and this is worth stating so the single finding is
not read as a trend:

- `SUBCOMMAND_SEPARATOR_CHARS` gained the newline and carriage return, so a
  pattern can no longer run past the end of its own command into the next line
  (Plan 00406).
- `normalise_line_continuations` now REMOVES the continuation rather than
  substituting a space, closing a real force push split mid-token — a fail-open
  direction that had reached every pattern built on the helper.
- `daemon_location_guard` and `plan_number_helper` now read through
  `get_bash_command`, so a line-continuation form they previously did not match
  at all is now matched.
- New denies: `issue_filing_gate` (R-UPSTREAM-ISSUE-UNVERIFIED-BODY),
  `reference_repo_freshness` (two rules), `plan_close_approval`,
  `merge_to_main_approval`, `R-WAIT-ON-WRAPPER-PID`.
- `documentation.qa.check_modes` gained `unenforced-approval-gate: block`, with
  the explicit reason that warning would establish a baseline.
- A zero-errors pyright gate was added to both `scripts/qa/run_all.sh` and CI.

**No handler default flipped to disabled. No severity was lowered. No
`exclude_paths`, `extra_whitelist` or per-handler opt-out was broadened.**

---

## Explicit non-findings

Recorded so a later run does not re-derive them.

1. **`handlers/registry.py`: `event_config.get(config_key) or {}`.** Reads as a
   widening; it is not. It fixes a crash: a bare `key:` in YAML parses to `None`,
   and `None.get(ENABLED, True)` raised outside the try block. The
   non-mapping-block-reads-as-enabled path
   (`config/models.py::coerce_handler_configs`, `else: result[name] =
   HandlerConfig()`) is byte-identical at `v3.63.0`, so a handler key written as
   a bare `false` silently meaning ENABLED is pre-existing. That is F-EXPT's
   question, not D-RULE's, and it is flagged here only so the delta run is not
   later blamed for missing it.
2. **`config/schema.py` deleted (-124).** The jsonschema `ConfigSchema` was never
   invoked by the daemon and hand-listed 3 event types against 31 wired ones. Its
   removal took away no check that ran.
3. **`scripts/qa/error_hiding_exclusions.json` (+105/-9).** Thirteen new
   exclusions, each keyed on file plus function-or-line, each carrying a written
   rationale and most naming a covering test. No path-glob widening; every
   deletion was a line-number realignment of an entry that still exists. The
   cumulative-union question is F-EXPT's.
4. **CI (`.github/workflows/qa.yml`, `scripts/qa/run_all.sh`).** Gates were
   added, not removed. `cancel-in-progress` now excludes the default branch so a
   release slate's exact-sha evidence is not destroyed — a release-evidence
   property with its own stated limit, not a security rule.

---

## Method notes

- Diff produced over the interval scoped to `src/` (248 files, +16178/-1252) and
  separately to everything outside `src/`, `tests/`, `CLAUDE/Plan/`, `docs/` and
  `RELEASES/`.
- Searched the src diff for removed or changed `get_default_enabled`,
  `default_enabled`, `Level.`, `severity`, `EXCLUDE`, `exclude_paths`,
  `whitelist`, `EXEMPT`, `terminal=`, `tags=[`, `Decision.` and `DENY`.
- Read in full: `constants/handlers.py`, `constants/rule_ids.py`,
  `constants/priority.py`, `handlers/registry.py`, `install/handler_profiles.py`,
  `config/validator.py`, `config/__init__.py`, `destructive_git.py`,
  `pipe_blocker.py`, `sensitive_content.py`, `daemon_location_guard.py`,
  `markdown_organization.py`, `tdd_enforcement.py`, `plan_number_helper.py`,
  `plan_qa_edit.py`, `utils/shell_segmentation.py`, `utils/command_evasion.py`,
  `utils/secret_file_matching.py`, `core/relevance.py`, `core/handler_bases.py`,
  `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yaml.example`.
- N1 was measured, not read: the two compiled patterns were reconstructed from
  their own source at each tag and driven over a shared case list. The probe
  scripts are `untracked/scratch/probe2.py` and `untracked/scratch/probe3.py`.
  Both currently fail `ruff` and could not be repaired: `Write` and `Edit` are
  disabled in this session, so this report was written through a Bash heredoc in
  parts and the probes could not be linted clean.
