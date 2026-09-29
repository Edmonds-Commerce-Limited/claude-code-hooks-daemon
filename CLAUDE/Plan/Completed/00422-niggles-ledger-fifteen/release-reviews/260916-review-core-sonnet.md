# Release code review — core/utils/install/daemon (v3.64.0..HEAD)

**Scope**: `git diff v3.64.0..HEAD -- src/` MINUS `handlers/`, `strategies/`,
`plan_qa/`, `docs_qa/`. That is 72 files: `utils/`, `core/`, `daemon/`,
`install/`, `constants/`, `config/`, `routines/` (new), `remote_docs/`,
`plan_finder.py`, `plan_links.py`, `rule_explain/`, `issue_report/`,
`skill_scan/`, `tool_report/`.

**Method**: read every changed file in scope; wrote executable probes against
the real modules for every claim below. Probes are in
`untracked/scratch/probe_*.py` and `untracked/scratch/*_demo*.sh`. Every
finding here was reproduced, none is inferred from reading alone.

**Could not run**: the project venv has no `pytest` installed and installing
deps needs network, so I did not run the suite. All evidence below comes from
direct invocation of the production modules instead, which is stronger
evidence for these specific claims anyway.

**Result**: 4 DEFECTS, 6 NON-DEFECTS. Two of the defects are fail-open gaps in
`shell_segmentation.py`; one of those is pre-existing, one is an incomplete
fix shipped *in this bundle*.

---

## DEFECT 1 — a bare-word `-m`/`-F` value swallows the command after it

**Location**: `src/claude_code_hooks_daemon/utils/shell_segmentation.py:243-253`
(`_MESSAGE_BODY_PATTERN`, the `|\S+` alternative on line 250)

**Failure scenario** (reproduced, `untracked/scratch/probe_destructive.py`):

| input | `strip_inert_spans` output | `destructive_git.matches()` |
| --- | --- | --- |
| `git reset --hard` | unchanged | DENY |
| `git commit -m x&&git reset --hard` | `git commit -m <REDACTED> reset --hard` | **ALLOW** |
| `git commit -m x;git reset --hard` | `git commit -m <REDACTED> reset --hard` | **ALLOW** |
| `git commit -m x&&git push --force origin main` | `git commit -m <REDACTED> push --force origin main` | **ALLOW** |
| `git commit -m x&&git clean -fd` | `git commit -m <REDACTED> clean -fd` | **ALLOW** |

Mechanism: the value alternatives are tried in order, and the last one is
`\S+`. `\S` matches `&`, `;` and `|`, so for an UNQUOTED message value the
regex greedily consumes the value, the separator, AND the next command's head
word. `git commit -m x&&git reset --hard` has its `x&&git` blanked to
`<REDACTED>`, leaving the scanner looking at `reset --hard` with no `git` in
front of it. Bash runs both commands; every guard downstream of
`strip_inert_spans` sees only one.

The gate conditions do not help here: `_segment_binary` resolves `git`,
`_segment_subcommand` resolves `commit` (which *is* in
`_MESSAGE_TAKING_SUBCOMMANDS`), and `value_can_substitute("x&&git")` is False
because there is no `$(`, `<(`, `>(` or backtick. All three checks pass and the
blanking proceeds.

**Reach**: every consumer of `strip_inert_spans` — `destructive_git`,
`pipe_blocker`, `daemon_location_guard`, `worktree_file_copy`,
`merge_to_main_approval` — plus `reference_repo_freshness`, which calls
`strip_message_bodies` directly. Reproduced against the utility for all of
them (`untracked/scratch/probe_other_guards.py`):

```
'git commit -m wip&&cd .claude/hooks-daemon'          -> 'git commit -m <REDACTED> .claude/hooks-daemon'
'git commit -m wip&&cp untracked/x ../wt/untracked/x' -> 'git commit -m <REDACTED> untracked/x ../wt/untracked/x'
'git tag -m note&&git push --force'                   -> 'git tag -m <REDACTED> push --force'
'git commit --message=wip&&git reset --hard'          -> 'git commit --message=<REDACTED> reset --hard'
```

**Not a regression from this bundle.** `_MESSAGE_BODY_PATTERN` is byte-identical
at `v3.64.0` (verified via `git show v3.64.0:...`). It is nonetheless a live
fail-open gap in a security-load-bearing utility, and the review brief asks for
defects regardless of vintage.

**DEFECT.**

**Suggested fix**: bound the bare-word alternative so it cannot cross a shell
metacharacter. Replace `r"|\S+"` with `r"|[^\s;&|<>()`]+"`. Verified against the
regression set (`untracked/scratch/probe_fix.py`) — it closes all four rows in
the table above while still blanking every legitimate case
(`-F commit-msg.txt`, `-m wip`, `--message=wip`, `-m 'document --hard'`):

```
'git commit -m x&&git reset --hard'  -> 'git commit -m <REDACTED>&&git reset --hard'   # separator preserved
'git commit -F commit-msg.txt'       -> 'git commit -F <REDACTED>'                     # still blanked
"git commit -m 'document --hard'"    -> 'git commit -m <REDACTED>'                     # still blanked
```

Add a regression test alongside `tests/unit/utils/test_shell_segmentation_inert_spans.py`
asserting that an unquoted value does not swallow the following command head.

---

## DEFECT 2 — the new command-substitution check is anchored, so a separator inside the substitution defeats it

**Location**: `src/claude_code_hooks_daemon/utils/shell_segmentation.py:119`
(`_SUBSTITUTION_OPENER_PATTERN`) and `:527-548` (`_receiver_is_data_sink`)

This bundle added the third heredoc check — "is the whole command inside a
SUBSTITUTION whose output lands in command position?" (commit `09851c57`,
Plan 00409). It is implemented as `re.compile(r"^(?:\$\(|`)")` matched against
the *lstripped receiving segment*. But `_receiving_segment` first splits on
`_RECEIVER_SEPARATORS` (`&&`, `||`, `;`, `|`, `&`) and takes the LAST piece — so
any separator inside the substitution moves the `$(` out of the segment and the
anchor never matches.

**Failure scenario** (reproduced, `untracked/scratch/probe_destructive.py`):

```python
"$(true && cat <<'EOF'\ngit reset --hard\nEOF\n)"    # -> body BLANKED, destructive_git: ALLOW
"$(echo x | cat <<'EOF'\ngit reset --hard\nEOF\n)"   # -> body BLANKED, destructive_git: ALLOW
"`true && cat <<'EOF'\ngit reset --hard\nEOF\n`"     # -> body BLANKED
```

versus the covered case, which the new test suite does pin:

```python
"$(cat <<'EOF'\ngit reset --hard\nEOF\n)"            # -> body kept, destructive_git: DENY
```

Bash really does execute the body in the uncovered form. Verified directly
(`untracked/scratch/subst_demo2.sh`):

```bash
$(true && cat <<'INNER'
echo LITERAL-COMMAND-POSITION-RAN
INNER
)
# prints: LITERAL-COMMAND-POSITION-RAN
```

Each check in `_blank_if_nothing_can_execute_it` answers "prose" here: the
receiver really is `cat`, nothing is piped downstream of the opener, and the
anchor misses. So the body is blanked and every caller is handed an empty
command while bash runs the real one — exactly the failure mode the Plan 00409
docstring on `strip_quoted_heredoc_bodies` describes.

`tests/unit/utils/test_shell_segmentation.py:384-398` covers only the
segment-leading spelling
(`test_a_sink_inside_a_command_substitution_keeps_its_body` and its backtick
twin). The separator variants are untested.

**DEFECT.** This one is in-bundle: the check is new here, and it is incomplete.

**Suggested fix**: decide substitution-containment from the RAW command text
around the opener rather than from the post-split segment. Concretely, in
`_receiver_is_data_sink`, before splitting, scan `command[:opener_start]` for an
unclosed `$(` / backtick (a depth counter over `split_unquoted`-style quote
tracking) and refuse when depth > 0. The existing anchored test then still
passes, and `$(true && cat <<'EOF'`, `$(echo x | cat <<'EOF'` and the backtick
spellings all withhold the exemption. Withholding costs a false positive, which
is the direction `DATA_SINKS`' own docstring already chooses.

Note the sibling, `_downstream_is_all_data_sinks`, is NOT affected — it reads
`opener_tail` directly and was already correct for `2>&1 | bash`.

---

## DEFECT 3 — the run ledger writes an escape it cannot read back, and drops the row silently

**Location**: `src/claude_code_hooks_daemon/routines/ledger.py:286-297`
(`_escaped` / `_unescaped`) and `:333-348` (`_split_row`)

`_escaped` writes `|` as `\|` so a note cannot break out of its column.
`_split_row` then does `stripped[1:-1].split("|")` — a raw split that does not
honour the backslash. A row whose note contains a pipe therefore yields 7 cells
instead of 6, fails the `len(cells) != len(_COLUMNS)` test, and returns `None`.
`_parse_file` `continue`s on `None`, so the row is dropped and is NOT added to
`unreadable`.

**Failure scenario** (reproduced, `untracked/scratch/probe_ledger.py`). A
routine records a start and a `findings` outcome whose note reads
`see report A | B for detail`:

```
| 2026-001 | 2026-09-16T12:00:00+00:00 | started  | -  | -  | -                            |
| 2026-001 | 2026-09-16T12:00:00+00:00 | findings | v1 | v2 | see report A \| B for detail |

events read   : 1              <- the terminal row vanished
malformed rows: []             <- and nothing reported it
run_states    : {'2026-001': RunState.FAILED}
next_from_ref : None
```

Three consequences, all wrong:

- a completed run with findings reads as `FAILED` (`run_states`, line 216 —
  `setdefault(..., FAILED)` with no terminal event to overwrite it);
- `next_from_ref` loses its anchor and returns `None`, so the next run has no
  `from` ref and the coverage chain restarts;
- `routines/qa.py:_ledger_unreadable` (`routine-ledger-unreadable`) stays
  silent, because `malformed_rows` never saw the row.

This is precisely the outcome `malformed_rows`' own docstring
(`ledger.py:178-190`) says must not happen: *"Skipping alone would trade a crash
for a silent omission, which is the worse of the two: a run would vanish from
the coverage chain with nothing saying so."* The escaping was written to prevent
it and the reader does not honour it.

A pipe in a note is not exotic — notes are free text supplied via
`hooks-daemon record-routine-run --note`, and a note citing a command or a
two-part reference produces one.

**DEFECT.**

**Suggested fix**: make `_split_row` escape-aware. The minimal change is a
negative-lookbehind split:

```python
_CELL_SPLIT: Final[re.Pattern[str]] = re.compile(r"(?<!\\)\|")
...
cells = [cell.strip() for cell in _CELL_SPLIT.split(stripped[1:-1])]
```

`_unescaped` already exists and is already applied in `_event_from_cells`, so
nothing else changes. Add a round-trip test: `append_event` a note containing
`|`, then assert `read_events` returns it verbatim and `malformed_rows` is
empty. Worth also asserting the negative — that a genuinely short row still
lands in `malformed_rows` rather than being dropped.

---

## DEFECT 4 — `stat()` sits outside the try that guards the same race

**Location**: `src/claude_code_hooks_daemon/utils/message_files.py:88`

```python
if not path_is_file(path, unreadable_means=False) or not os.access(path, os.R_OK):
    continue
if path.stat().st_size > MAX_MESSAGE_FILE_BYTES:   # <-- unguarded
    continue
try:
    raw_bytes = path.read_bytes()
except OSError as failure:
    # "Statting a file is NOT reading it, and the gap raises. ... one
    #  unlinked between the check above and this line. Letting that escape
    #  takes the calling guard down with it"
    continue
```

The comment on lines 92-99 reasons correctly about the check-then-use race and
wraps `read_bytes`. The `stat()` on line 88 is in the same window and is not
wrapped. A file unlinked between `path_is_file` and `stat`, or one on a mount
that returns EIO, raises `OSError` out of `read_message_files` and takes the
calling guard down with it — which for `sensitive_content` means a guard that
either silently stops applying (`strict_mode: false`, the client default) or
denies legitimate work (`strict_mode: true`). That is the exact failure the
surrounding code was written to avoid.

The window is narrow and I did not force it, so likelihood is low; the
inconsistency is unambiguous and the module itself states the rule it breaks.

**DEFECT.**

**Suggested fix**: move the size check inside the existing `try`, or read
through `path.stat()` inside it:

```python
try:
    if path.stat().st_size > MAX_MESSAGE_FILE_BYTES:
        continue
    raw_bytes = path.read_bytes()
except OSError as failure:
    _LOGGER.debug("Skipping unreadable message file %s: %s", path, failure)
    continue
```

---

## Known-open, owner-ruled — NOT a release blocker

### `${VAR:-default}` interpolation in the generated forwarder

**Location**: `src/claude_code_hooks_daemon/install/forwarder_generator.py:284`
and `:290` (`_rl_events_dir`, `_rl_bin`)

This bundle escaped three of five interpolation sites via
`_escape_for_double_quotes`. The two `${VAR:-default}` sites are deliberately
left unescaped, and the in-code comment says so. Confirmed that the value is
live there (`untracked/scratch/interp_demo.sh`):

```bash
_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/tmp/proj$(echo INJECTED)/relay}"
echo "$_rl_bin"   # prints /tmp/projINJECTED/relay
```

So a checkout whose absolute path contains `$(...)`, a backtick or `}` emits a
forwarder that runs a substitution on every hook invocation when the daemon is
down.

`CLAUDE/Plan/Completed/00412-.../DECISION-forwarder-interpolation-contexts.md`
records this as **DECIDED** — option B endorsed, unbuilt, and explicitly
"nothing is claimed to be closed that is not". It is a real gap, it is
accurately recorded, and the owner has already ruled on it. **Raising it as a
release blocker would re-litigate a decision that was made.** Listed here only
so the release gate's record is complete.

---

## Non-defects

1. **`utils/markdown_links.py:16` contradicts its own docstring and inverts the
   layering.** The module docstring says *"It lives in `utils` rather than in
   either subsystem so the dependency runs one way: both QA packages import it,
   and it imports neither of them."* It then imports
   `claude_code_hooks_daemon.plan_qa.model.lines_outside_fences`. Since
   `docs_qa/corpus.py` and `docs_qa/checks/pointer_resolves.py` import this
   module, `docs_qa` now transitively depends on `plan_qa`. No cycle today
   (`plan_qa/model.py` does not import `utils.markdown_links`), but it is one
   edit away from one, and the false docstring is the bigger problem — a future
   reader will trust it. **Fix**: move `lines_outside_fences` into `utils` too
   (it is a pure text helper with no plan-QA semantics), or correct the
   docstring to state the real direction. NON-DEFECT.

2. **`daemon/background_harvester.py:240` — `tree_pgids` is not filtered against
   `exclude_pgids`.** `find_breaches` excludes a breaching record whose own
   `pgid` is excluded (line 201), but `Breach.tree_pgids` is built from the whole
   descendant tree with no such filter, and `kill_command` emits
   `kill -- -<pgid>` for every one of them. The only caller passes
   `exclude_pgids=(os.getpgrp(),)` — the harvester's own group. If a descendant
   ever lands in that group the suggested command names the group the exclusion
   exists to protect. I could not construct a realistic way for that to happen
   (a descendant normally keeps or creates its own group), so this is hardening
   rather than a live bug. **Fix**: drop excluded pgids when building
   `tree_pgids`, so the exclusion holds for the whole `Breach`, not just the
   flagging decision. NON-DEFECT.

3. **`install/skills.py:56-63` — `_trees_match` reads the source tree twice.**
   `_relative_files(source)` is called on line 60 (comparison) and again on line
   63 (the generator). Install-time only and small trees, so cost is negligible;
   hoisting it to a local is one line and reads better. NON-DEFECT (style).

4. **`install/skills.py:77-81` — the backup counter skips `-1`.** `suffix`
   starts at 1 and is incremented before first use, so the alternatives are
   `<name>`, `<name>-2`, `<name>-3`. Harmless and unambiguous; noting only
   because a reader may expect `-1`. NON-DEFECT (cosmetic).

5. **`utils/cron_enforcement.py:144` — `_was_truncated`'s length fallback uses
   `>=`.** A declared prompt of exactly `PROMPT_DELIVERY_CAP` characters
   delivered in full is read as truncated, so matching falls back to
   `startswith` prefix comparison. The fallback errs toward *accepting* a match,
   which for a Stop-blocking gate is the safe direction (it under-blocks rather
   than blocking every stop), and the docstring says that is deliberate for
   exactly this reason. NON-DEFECT.

6. **`utils/host_identity.py:259-263` — a rejected local hostname short-circuits
   the ladder.** On a host (or LXC), if `socket.gethostname()` fails
   `_clean_host_name`, the function returns `None` immediately rather than
   falling through to the `/etc/hosts` rung. Defensible (on a host the hint adds
   nothing `gethostname` could not say), and the module presents itself as a
   first-hit-wins ladder, so this is consistent. Noting only because the
   docstring's numbered ladder reads as though rung 3 is always tried.
   NON-DEFECT.

---

## What is done well

- **`DATA_SINKS` as an allowlist with an explicit exclusion list**
  (`shell_segmentation.py:184-231`). The `sqlite3`/`psql`/`mysql` removals name
  the shell-escape mechanism rather than the command, which is the right level
  of specificity — the test pins the escape, so a future reader cannot re-add
  them by arguing "it just reads stdin".
- **`_downstream_is_all_data_sinks` and `_FD_REDIRECT_PATTERN`.** Both fix real,
  reproducible holes (`cat <<'EOF' 2>&1 | bash`) and both come with a paired
  control test asserting the fix did not withhold the exemption from genuine
  sinks (`test_a_stderr_redirect_before_a_sink_still_blanks`). That pairing is
  the difference between a fix and a regression.
- **`remote_docs/capture.py:177-198`** — replacing frontmatter string
  interpolation with `yaml.safe_dump`. The comment names the concrete exploit
  (`licence: "MIT\nfidelity: verbatim"`) rather than gesturing at "injection".
- **`remote_docs/store.py:160-217`** — `content_guard` on the refresh path,
  scanned *before* the unchanged-hash short-circuit so the short-circuit cannot
  become a route past the guard. `REFUSED` as a distinct outcome from `FAILED`
  is the right call.
- **`core/session_start_tiers.py`** — `ACTION_REQUIRED` computable-only, with
  the `declared_tier` clamp at line 180 as defence-in-depth against a directly
  set attribute. The `has_verifier` identity check against the mixin's own
  unbound default is a neat way to distinguish "mixed in but not implemented"
  from "implemented and passing".
- **`utils/path_predicates.py`** — `unreadable_means` as a required keyword
  argument with no default. The docstring's justification (73 call sites that
  provably disagree about the safe answer) is the strongest argument in the
  diff.
- **`utils/operator_signal.py` / `session_actions_signal.py`** — closed `kind`
  set, integer-only payload, `type(count) is not int` to reject `bool`, and
  rendering kept entirely on the supervisor side. A channel that structurally
  cannot carry prose is the right shape for one reachable from outside the
  container.
- **Test coverage is genuinely behavioural.** `test_shell_segmentation.py`'s
  new class tests outcomes (`"git reset --hard HEAD" in stripped`) against
  named attack shapes, not implementation details. Every new module in scope
  has a test file in the same bundle.

---

## Verdict

**REQUEST CHANGES** — 4 defects, 2 of them fail-open gaps in the
destructive-command path.

Ordered by what I would fix first:

1. DEFECT 2 (`_SUBSTITUTION_OPENER_PATTERN` anchoring) — new in this bundle, an
   incomplete fix shipping as a complete one.
2. DEFECT 1 (`\S+` message value) — pre-existing but wider reach: five guards,
   four confirmed ALLOWs on destructive git commands.
3. DEFECT 3 (ledger escape round trip) — silent data loss in a new subsystem,
   and the fix is a two-line regex.
4. DEFECT 4 (`stat()` outside the try) — one-line move, low likelihood.

The forwarder interpolation item is owner-ruled and recorded; it should not
gate this release.
