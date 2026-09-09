# Code Review: v3.63.0 release gate — install / plan_qa / docs_qa / skills

## Summary

The slice is high quality: dense rationale comments, measured design decisions,
and broad test coverage (2342 unit tests in the reviewed packages pass, plus 29
integration tests for the skill surface and settings merge). One newly shipped
shell helper has a silent total-data-loss path that returns success, which is
the single blocking finding. The rest are non-blocking.

Reviewed: 49 source files, ~3280 insertions / ~848 deletions, `v3.62.1..HEAD`.
Scope: `install/`, `plan_qa/`, `docs_qa/`, `skills/`.

Issues found: 1 BLOCKER, 15 NOTE.

Test coverage per changed module was checked against
`git diff v3.62.1..HEAD --name-only -- tests/`. Every changed and every new
module in the slice has a corresponding test file. New modules
`version_parse.py`, `handler_key_audit.py` and `settings_merge.py` have
dedicated suites (`test_version_parse.py` 125 lines, `test_handler_key_audit.py`
319 lines, `test_settings_merge.py` + `test_settings_merge_run.py` 540 lines).

Verification performed for this review:

| Check                                          | Result                  |
| ---------------------------------------------- | ----------------------- |
| `pytest tests/unit/{install,plan_qa,docs_qa}/`  | 2342 passed             |
| Skill surface + settings-merge integration      | 29 passed               |
| Debug code / TODO / FIXME / noqa in added lines | none found              |
| Housekeeping doc table vs `housekeeping --list` | 20 steps, exact match   |
| Every CLI verb named in skill markdown          | all present in `--help` |

---

## Critical Issues

### 1. `echd-capture` discards the entire stream and exits 0 when its capture directory is unwritable (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/install/templates/echd-capture:73`,
`:89`, `:91-92`, `:102`

**Problem:**

The script runs under `set -uo pipefail` with no `-e` and no error handling on
the two operations that must succeed. If `mkdir -p "$_dir"` fails, execution
continues; `cat > "$_capture"` then fails and the piped stream is consumed and
thrown away; `wc -l` fails leaving `_total_lines` empty; the footer prints a
path to a file that does not exist. The script exits 0.

This is the helper `pipe_blocker`'s deny message tells every agent to use
*instead of* a truncating pipe, on the stated grounds that truncating an
expensive command's output loses data. In this failure mode it loses all of it
and reports success.

**Evidence:**

Reproduction saved at
`untracked/agent-reports/echd-capture-failure-probe.sh`.

```
$ printf 'a\nb\nc\n' | ECHD_CAPTURE_DIR=/proc/nonexistent/nope bash echd-capture 2
exit=0
--- stdout ---

--- echd-capture: showing tail 2 of  lines ( bytes total) ---
(full output: /proc/nonexistent/nope/command-output-1788943818-1319475.txt)
--- stderr ---
mkdir: cannot create directory '/proc/nonexistent': No such file or directory
echd-capture: line 89: /proc/.../command-output-....txt: No such file or directory
tail: cannot open '/proc/.../command-output-....txt' for reading
echd-capture: line 102: [: : integer expression expected
```

The three input lines appear nowhere in stdout.

**Why It Matters:**

An agent runs a test suite through the helper, sees an empty preview and a path,
and concludes the run produced no output. The wrong conclusion is drawn
silently. Triggers are ordinary rather than exotic: a read-only `/tmp` in a
hardened container, a full disk, or an operator-set `ECHD_CAPTURE_DIR` naming a
path whose parent does not exist. The precedence chain at `:66-71` falls back to
`${TMPDIR:-/tmp}/echd-captures`, but an explicit `ECHD_CAPTURE_DIR` has no
fallback at all.

Once this ships, clients have the broken copy on disk. That is the exact
argument the self-bootstrap stanza in the sibling skill scripts makes for itself.

**Suggested Fix:**

Fail the directory setup loudly and stream through instead of eating the input:

```bash
if ! mkdir -p "$_dir" 2>&1; then
    echo "echd-capture: cannot create capture dir $_dir — passing output through unchanged" >&2
    exec cat
fi
```

and guard the capture write the same way
(`cat > "$_capture" || { echo ... >&2; exit 1; }`). `exec cat` is the right
degradation: the caller still sees every byte, which is the property the helper
exists to guarantee. Add a test for the unwritable-dir case —
`tests/integration/test_echd_capture.py` currently has seven tests and none of
them exercises an error path (also no coverage of `--label`, `--all`, or the
exit-2 bad-argument branch at `:33-36`).

---

## Important Issues

### 2. `append_nc_socket_arg` is not idempotent against the previous release's generated form (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/install/forwarder_generator.py:431`

**Problem:**

The idempotency guard was changed from `existing_args[-1] == event_file_name` to
`len(existing_args) >= 2 and existing_args[-2] == event_file_name`. A forwarder
generated by v3.62.1 carries three args (`"PreToolUse" "" "pre-tool-use"`), so
`existing_args[-2]` is the empty string, the guard does not fire, and two more
args are appended.

**Evidence:**

Probe saved at `untracked/agent-reports/probe_forwarder.py`.

```
LEGACY IN : 'send_request_stdin "PreToolUse" "" "pre-tool-use"'
REGEN OUT : 'send_request_stdin "PreToolUse" "" "pre-tool-use" "pre-tool-use" ""'
STOP LEGACY OUT: 'forward_stop_event "Stop" "stop" "stop" ""'
```

The 4th positional argument is the events-directory override, so the bash key
`"pre-tool-use"` is handed to `send_request_stdin` as an events directory and
the nc rung looks for a relative socket path.

**Why It Matters:**

Reachable through `install/transport_toggle.py:386` and `:411`, which call
`regenerate_deployed_hooks` over already-deployed files with no preceding copy.
The install and upgrade paths re-copy the source first
(`scripts/install/hooks_deploy.sh`), so this is confined to a
`transport relay on|off` toggle performed on an nc-enabled install that has not
been redeployed since v3.62.1. Both `relay_enabled` and `nc_enabled` default to
`False`, which is why this is not blocking.

The docstring at `:398-403` claims idempotency; it holds only against this
release's own output.

**Suggested Fix:**

Make the guard positional rather than relative to the end — the bash key always
lands at index 2 for `send_request_stdin` and index 1 for `forward_stop_event`:

```python
key_index = 2 if func == "send_request_stdin" else 1
if len(existing_args) > key_index and existing_args[key_index] == event_file_name:
    existing_args = existing_args[: key_index + 1]  # drop stale trailing args
```

Add a regression test that feeds the v3.62.1 three-argument form through
`generate_forwarder_content` and asserts the result carries exactly four
arguments. `tests/unit/install/test_forwarder_generator.py:447` and `:523` test
idempotency only against freshly generated content, so both pass today.

---

### 3. Commit-stage plan QA spawns one `git diff` per plan folder (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/plan_qa/checks/common.py:416`
(`commit_touches_plan`), called from
`src/claude_code_hooks_daemon/plan_qa/checks/row_folder_bijection.py:51`

**Problem:**

`commit_touches_plan` calls `GitFacts.staged_changes()`, which spawns a
`git diff` subprocess every time (`plan_qa/gitfacts.py:59`, no memoisation
anywhere in that class). `row_folder_bijection._folder_findings` computes `level`
before deciding whether there is a finding at all, so the call fires once per
plan folder in the tree regardless of outcome.

**Evidence:**

Probes saved at `untracked/agent-reports/probe_commit_gate.py` and
`probe_commit_gate_cached.py`. Same repository, same three findings:

| Variant                          | git spawns | Elapsed |
| -------------------------------- | ---------- | ------- |
| As shipped                       | 363        | 0.78 s  |
| With `staged_changes()` memoised | 1          | 0.03 s  |

**Why It Matters:**

This runs inside the `git commit` PreToolUse gate. The cost scales linearly with
plan count, so it grows for exactly the projects that use the plan workflow most.
It is a regression introduced by this slice — before Plan 00343 Phase 3 the level
was a set membership test with no git access.

**Suggested Fix:**

Memoise `staged_changes()` on the `GitFacts` instance. The object is constructed
per context in `plan_qa/context.py:232` and `:279` and is read-only for its
lifetime, so a `functools.cached_property` or a simple `self._staged` guard is
safe and needs no invalidation. Separately, move the `_level(...)` call in
`row_folder_bijection._folder_findings` below the `if not rows` and section
checks so it is computed only when a finding is actually emitted.

---

### 4. Skill `report` subcommand interpolates its argument into a stream-editor script (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md:220`

**Problem:**

The `report` branch pipes `report.md` through a substitution whose replacement
text is the raw `$*` (the user-supplied description). Bash expands it into the
editor *script*, not into a data slot. A `/` in the argument terminates the
replacement and the remainder is parsed as further editor commands. The GNU
implementation supports an `e` command that executes its argument as a shell
command, so an argument shaped `x/;e <command>` produces a script that runs it.

I did not execute a proof: this project's own guard denies any Bash command
naming that tool, so the reproduction is not runnable here. The mechanism is the
documented `e` command combined with unquoted-delimiter injection. The exact
command line is quoted in the reviewer's return message.

**Why It Matters:**

Practical escalation is limited because the caller already has Bash, so this is
not a privilege boundary crossing. It is still an injection sink in an artefact
shipped to every client, and it breaks on a benign argument containing a slash
(a file path in the description) long before anyone abuses it. It is pre-existing
rather than introduced by this diff, but this release rewrites the surrounding
routing block.

**Suggested Fix:**

Use bash parameter expansion, which substitutes literally and cannot be escaped:

```bash
_report="$(cat "$SKILL_DIR/report.md")"
printf '%s\n' "${_report//\$ARGUMENTS/$*}"
```

This also removes a tool dependency that the project's own guard forbids
elsewhere.

---

## Suggestions

- **`client_validator.py:176`** — the deployed helper path is four string
  literals (`project_root / ".claude" / "hooks-daemon" / "bin" / "echd-capture"`)
  while `DaemonPath.CLAUDE_DIR`, `DaemonPath.HOOKS_DAEMON_DIR`,
  `bin_wrapper.BIN_DIR_NAME` and `bin_wrapper.ECHD_CAPTURE_NAME` all exist and
  are what `deploy_echd_capture` uses. Renaming the helper breaks this check
  silently. Compose the path from the constants.

- **`handler_key_audit.py:53-58`** — `_DEFAULT_PSEUDO_EVENT_BLOCKS` hardcodes
  `["pre_tool_use:1/5", "stop:1/1"]` with the comment "Triggers match the
  reference config", while the module docstring says nothing here consults the
  reference config. The two agree today (`.claude/hooks-daemon.yaml:1181-1183`)
  and nothing pins them: `tests/unit/install/test_handler_key_audit.py:204`
  asserts only that the trigger list is truthy. Add an assertion comparing the
  constant to the shipped reference/example config.

- **`handler_key_audit.py:183`** — calls `ConfigValidator._find_similar_names`,
  a private method of another class. Promote it to a public helper on
  `ConfigValidator` (or into a shared module) so the dependency is declared.

- **`handler_key_audit.py:320`** — `_fill_block_defaults` falls back to
  `{_ENABLED: True}` for any pseudo-event not in `_DEFAULT_PSEUDO_EVENT_BLOCKS`,
  producing a block that is enabled with no triggers. By this module's own
  reasoning (`scaffold_pseudo_event_blocks` docstring: "a block with handlers but
  no triggers never fires") that is the moved handler retired a second time.
  Only `nitpick` is a relocation target today, so nothing hits it — make the
  fallback raise, or require every relocation target to have a default block.

- **`same_commit_plan_doc.py:82`** — `except OSError` around
  `candidate.read_text(encoding="utf-8")`; a non-UTF-8 `PLAN.md` raises
  `UnicodeDecodeError` (a `ValueError`) and propagates out of the commit gate.
  Elsewhere in this codebase the pair is caught together, e.g.
  `forwarder_generator.py:567` and `docs_qa/corpus.py:880`. Use
  `except (OSError, UnicodeDecodeError)`.

- **`forwarder_generator.py:97`** — `meta.daemon_down_stdout` is interpolated
  into a double-quoted shell `echo` with no escaping. The value comes from the
  internal event catalogue so nothing is exploitable, but a future entry
  containing a double quote, a dollar sign or a backtick would emit a broken or
  command-substituting forwarder. Escape it, or assert at catalogue level that
  the field is shell-safe. Also,
  `_render_raw_stdout_daemon_down_block` rebuilds `metas_by_bash_key` from
  `wired_event_metas()` on every call; hoist it.

- **`transport_verify.py:293-299`** — when the daemon is down, the Stop forwarder
  emits a `decision: block` body on stdout with exit 0 (`.claude/init.sh`
  `emit_hook_error`), so the probe correctly fails but reports "exit-code
  translation broken", which points the operator at the wrong subsystem. Add a
  `_DAEMON_ERROR_MARKER in err` test ahead of that branch and report the outage.

- **`settings_merge.py:465`** — the comment says "every whole-file writer is
  atomic or can be", but `client_path.write_text` at `:473` (and `:424`) is not
  atomic. Either write via a temp file and `Path.replace` (the idiom
  `docs_qa/corpus.py:_save_corpus` already uses), or reword the comment so it
  does not assert a property the code lacks.

- **`echd-capture:71`** — `${TMPDIR:-/tmp}/echd-captures` is a fixed name in a
  world-writable directory. `mkdir -p` follows a pre-existing symlink, so a local
  attacker who wins the race can redirect captures. Low severity and last-resort
  only, but `mktemp -d` or an ownership check would close it. Observed in
  practice during this review: the fallback fired because `CLAUDE_PROJECT_DIR`
  was unset in my shell.

- **`echd-capture:88`** — the comment says "Tee the FULL stream to the capture
  file" but the code is `cat > "$_capture"`, which does not tee. Reword.

- **`echd-capture:30`** — `-h|--help` runs a comment-extraction pipeline that
  prints every comment line in the file, not just the header block. Terminate at
  the first non-comment line.

- **`SKILL.md:3`** — the `description` frontmatter lists "install, upgrade, check
  health, restart, run the housekeeping pass, and report issues" and omits
  `optimise`, while `argument-hint` on the next line lists all eight. Align them.

- **`dev-handlers.md:22`** — the copy-paste block ends with a literal `"$@"`.
  Pasted into a shell, that expands to the caller's own positional parameters,
  normally empty. Use a `[args...]` placeholder or drop it.

- **`docs_qa/corpus.py:873`** — `revalidate_corpus` logs an unstattable file at
  `logger.debug` and drops it. The rationale is written out and correct, but
  `debug` means an unexpected `EACCES` is invisible at default log level. `info`
  would keep it traceable without noise.

## Positive Observations

- **Rationale density is exceptional.** Nearly every non-obvious branch carries a
  comment explaining the failure it was written against, with the plan number.
  `settings_merge.py`'s module docstring stating that copy direction *is* the
  safety property, and `same_commit_plan_doc.py`'s docstring recording a measured
  25% false-positive rate as the reason for subject-line scoping, are both the
  right way to justify a design.

- **Plan 00295's walk consolidation is a genuine DRY win.** Two near-identical
  `os.walk` loops in `module_doc_budget.py` and `source_tree_markdown.py`
  collapsed into `corpus.iter_markdown_paths` with an `also_prune` hook, and the
  sweep now performs the walk once via `CheckContext.markdown_paths`. Both checks
  kept a fallback for contexts built another way, so no caller broke.

- **`_derive_record` in `corpus.py`** removes a three-way copy of the record
  construction with an explicit note about the add-a-field-in-three-places
  hazard. That is the correct reason to extract.

- **The skill surface is genuinely coherent with the code.**
  `housekeeping --list` emits 20 steps in the same order and with the same
  dispositions as the table in `housekeeping.md`, and every CLI verb named across
  the skill markdown resolves in `--help`. Two integration suites
  (`test_skill_surface_coherence.py`, `test_deployed_skill_trees.py`, 514 lines)
  exist to keep it that way.

- **`optimise` moving from a hand-kept five-area list to a registry-derived
  checklist** removes the whole class of "handler shipped but never scored".

- **`transport_verify.py:145-153`** reaps a timed-out probe child before
  re-raising, preserving the caller's existing `TimeoutExpired` handling. A small
  fix, correctly scoped.

- **Tests are behavioural, not theatre.** Spot-checked
  `test_handler_key_audit.py`, `test_settings_merge.py` and
  `test_forwarder_generator.py`: they assert on outcomes and messages, use real
  config fixtures, and several encode the specific field-report shape the code
  was written for.

## Verdict

REQUEST CHANGES — finding 1 must be fixed before release.

Findings 2, 3 and 4, and every suggestion, are non-blocking and should be filed
as plan tasks by the dispatching session.
