# Code Review: Plan 00460 (worktree-plan-460-report-size, main...89cb2256)

**Reviewer**: code-reviewer (Opus 5.5)
**Scope**: `git diff main...89cb2256`, 29 files, +4,741/-49. Source reviewed in full:
`utils/subagent_tool_resolution.py`, `utils/subagent_report_paths.py`,
`handlers/subagent_stop/subagent_report_persistence.py`, the size blocker and
`dispatch_declaration` diffs, `utils/markdown_format.py`, config/registration,
error-hiding exclusions, the release note, and all new/changed tests.

**Verdict**: REQUEST CHANGES. The Task 1.1-1.5 work (resolver, condense path,
dispatch advisory) is sound apart from one precedence bug. The Task 1.6
persister has two blocker-level problems: it writes unvetted reply content
into client working trees that are not guaranteed to be gitignored, and its
retention sweep deletes reports that agents were deliberately told to write
into the same directory.

**Counts**: 2 blocker, 4 major, 11 minor.

## Evidence probe

`/workspace/untracked/scratch/plan460-review/probe_plan460.py` (kept as evidence).
Run from the main checkout:

```
W=/workspace/untracked/worktrees/worktree-plan-460-report-size
S=/workspace/untracked/scratch/plan460-review/run-$(date +%s); mkdir -p "$S"
PYTHONPATH=$W/src $W/untracked/venv-workspace_untracked_worktrees_worktr-2ab3-py311-81c29529/bin/python \
  /workspace/untracked/scratch/plan460-review/probe_plan460.py "$S"
```

Output at review time:

```
P1 agent-authored 40-day-old report survives: False
P2 README.md survives report_dir='': False ['260924-141902-general-purpose-abc123.md']
P3 files written outside root: ['260924-141902-general-purpose-abc123.md']
P4 git status in client repo: ?? untracked/agent-reports/260924-141902-general-purpose-abc123.md
P5 'most recent' picked: 260924-120000-Explore-abc123.md
P6 matches on stop_hook_active=True: False
P7 overridden Explore (tools include Write) resolves: False
P8 blocker points at: ['.../p8/untracked/agent-reports/260920-100000-general-purpose-abc123.md']
```

---

## Blockers

### B1. Unvetted reply content lands in client working trees that nothing guarantees are gitignored (Confidence 95%)

**Location**: `src/claude_code_hooks_daemon/handlers/subagent_stop/subagent_report_persistence.py:121-164`;
`utils/subagent_report_paths.py:40,106-107`; `daemon/init_config.py:366`;
`tests/unit/utils/test_subagent_report_paths.py:148-163`.

**Problem**: The persister writes every `last_assistant_message` to
`<project_root>/untracked/agent-reports/` and creates the directory tree
(`mkdir(parents=True)`) if missing. The ONLY evidence that this path is
gitignored is `test_is_actually_gitignored_in_this_repo`, which checks THIS
repository's `.gitignore`. Nothing checks it at runtime. `untracked/` at the
project root is this repo's convention; the daemon's guaranteed-ignored area
in a client is `.claude/hooks-daemon/untracked/`, and
`gitignore_safety_checker` does not list `untracked/`. The handler is enabled
when absent from config (`registry.config_skip_reason`: absent means enabled)
and is in the shipped default config, so every upgrading client gets it.

The design rationale ("saving it to a path git never sees discloses nothing
new", persistence docstring lines 14-20; `subagent_report_paths.py` lines 8-12)
is exactly the reasoning Task 1.2 rejected for option (a): the content gets no
sensitive-content, secret-word-list or markdown-location check. The claim that
it "already reaches Claude Code's on-disk transcript" is not equivalent: the
transcript lives under `~/.claude/projects/`, outside the repo; this file lives
INSIDE the working tree, where `git add -A`, a Docker build context, rsync
deploys, IDE indexing and cloud-synced folders all see it.

**Failure scenario** (probe P4): a client repo whose `.gitignore` has no
`untracked/` entry. A security-reviewer sub-agent quotes a credential it found
in a config file in its final reply. The daemon writes it to
`untracked/agent-reports/<ts>-security-reviewer-<id>.md`; `git status` shows
`?? untracked/agent-reports/...`; the next `git add -A && git commit` records
it. The commit-time `sensitive_content` scan only catches configured
patterns/terms, not arbitrary secrets.

**Suggested fix** (any one is sufficient, first is simplest):
1. When `write_new_file_never_overwrite` creates the report directory, also
   create `<report_dir>/.gitignore` containing `*` (a self-ignoring
   directory), so the guarantee travels with the directory in every project.
2. Or: once per daemon lifetime, run `git check-ignore -q <report_dir>/probe.md`;
   if the path is NOT ignored, skip persistence, log at WARNING, and emit a
   one-time advisory telling the operator to add the entry.
3. Or: default to a directory under `ProjectContext.daemon_untracked_dir()`,
   which the installer already keeps ignored.
Also update the docstrings/release note that assert "gitignored"
unconditionally (see m7), and add a test that runs the handler against a
`git init` tmp repo with no ignore rule and asserts the file is not
committable (or not written).

### B2. Retention sweep deletes reports agents were deliberately told to write in the same directory (Confidence 95%)

**Location**: `subagent_report_persistence.py:63-67,146-164`;
`dispatch_declaration.py:56` (`_DEFAULT_FALLBACK_REPORT_DIR = DEFAULT_REPORT_DIR`);
`subagent_report_size_blocker.py:54` (fallback dir `untracked/agent-reports/`);
`install/templates/core/PlanWorkflow.core.md:204`.

**Problem**: `prune_directory(target_dir, pattern="*.md", ...)` deletes EVERY
`.md` in `untracked/agent-reports/` that is older than 30 days or beyond the
newest 500. That same directory is the documented, coordinator-declared
destination for non-plan work (`dispatch_declaration` fallback, the
PlanWorkflow template) and the size blocker's own fallback path for writable
agents. Those files are deliberate deliverables, not daemon cache. Before this
change nothing pruned that directory; after merge, the first SubagentStop
deletes any authored report past 30 days, silently (retention logs only
failures).

**Failure scenario** (probe P1, and real data): `/workspace/untracked/agent-reports/`
in the main checkout today holds 22 agent-authored reports dated 260915-260923
(e.g. `260915-claude-code-guide-haiku.md`, `260916-release-delta-classifier-opus.md`).
From about 2026-10-15 the first sub-agent stop deletes them, one day's worth
at a time. A client that declared `untracked/agent-reports/` as its non-plan
destination loses reports the same way.

**Suggested fix**: Persist into a dedicated subdirectory that only the daemon
writes, for example `untracked/agent-reports/auto/` (or a separate
`untracked/agent-replies/`), and prune only there. If the directory must stay
shared, filter prune candidates in Python by the exact persisted-name regex
`^\d{6}-\d{6}-.+\.md$`. Note that the glob `??????-??????-*.md` is NOT safe
enough: `260916-review-core-sonnet.md` matches it because "review" is six
characters. Add a test that seeds an old agent-authored `yymmdd-name-model.md`
file and asserts it survives a persist+prune.

---

## Major

### M1. `report_dir` is unvalidated: an empty, `.`, absolute or `..` value writes outside the intended tree and prunes arbitrary markdown (Confidence 90%)

**Location**: `subagent_report_persistence.py:121-122` (`self._root() / self._report_dir`)
and the prune call at 149-164; `.claude/hooks-daemon.yaml.example` advertises
`options.report_dir`.

**Failure scenario** (probes P2, P3): `report_dir: ""` or `"."` makes the target
the project root. The next stop prunes `*.md` there by age, so `README.md`,
`CLAUDE.md`, `CHANGELOG.md` older than 30 days are unlinked (P2 shows README.md
deleted). An absolute `report_dir` (`Path / "/abs"` discards the root) writes
and prunes outside the repository (P3); `"../docs"` does the same one level up.
`project_containment` does not apply because this is the daemon's own write.

**Suggested fix**: Validate at use: reject (log WARNING, skip persistence)
unless `report_dir` is non-empty, relative, contains no `..` segment, and
`(root / report_dir).resolve()` is strictly inside `root.resolve()` and not
equal to it. Combined with the B2 name filter, pruning can then never touch a
file the persister did not create. Add tests for `""`, `"."`, `"/tmp/x"`,
`"../x"`.

### M2. "Every sub-agent's final reply" is not persisted: the re-entry guard drops the real final reply after any SubagentStop block (Confidence 85%)

**Location**: `subagent_report_persistence.py:100-102`; test pinning it at
`tests/unit/handlers/subagent_stop/test_subagent_report_persistence.py:68-70`.

**Problem**: `matches()` returns False when `stop_hook_active` is true, copied
from the BLOCKING siblings where it prevents a deny loop. A sensor that always
ALLOWs has no loop to prevent. Claude Code sets `stop_hook_active` on every
stop that follows a stop-hook block, so after `subagent_report_path_verifier`
(8), `cron_subagent_stop_enforcer` (7) or the size blocker (15) blocks, the
agent's continued work and its ACTUAL final reply are never persisted. The
file on disk is the pre-correction attempt.

**Failure scenario** (probe P6): the cron enforcer blocks an agent's first
stop; the agent keeps working for many turns and returns its real report on a
re-entry stop. `untracked/agent-reports/` holds only the first, superseded
reply. The plan's goal, success criterion and release note all say "every".

**Suggested fix**: Match every SubagentStop (drop the guard; persistence of a
second file per agent is harmless and the collision suffix already exists).
The size blocker is unaffected because it does not run on re-entry. Replace
`test_does_not_match_re_entry` with a test asserting a re-entry reply IS
saved as a second file.

### M3. The size blocker tells the agent its reply was saved "through the content-safe daemon path" (Confidence 90%)

**Location**: `subagent_report_size_blocker.py` `_deny_saved`, the
`bash_warning` string (diff lines around 146-152 of the new file): "the file
above is already saved through the content-safe daemon path".

**Problem**: The persister deliberately runs NO content checks (its own
docstring, lines 14-20). The message asserts a safety property that does not
exist, to an LLM that will relay it to the coordinator. This is the same class
of false assurance CLAUDE.md warns about ("A Bash write that drew no complaint
is NOT a write that passed those checks").

**Suggested fix**: Reword to state only what is true, e.g. "the daemon has
already saved the full text to the path above, so there is nothing for you to
write". Add a test asserting the reason does not claim content checking.

### M4. The resolver consults built-ins before project/user agents, but upstream says a custom agent named `Explore` overrides the built-in (Confidence 85%)

**Location**: `utils/subagent_tool_resolution.py:155-163`.

**Problem**: The vendored doc `remote-docs/code.claude.com/docs/en/sub-agents.md:55`
states "A user or project subagent named `Explore` overrides the built-in", and
recommends doing exactly that (`model: haiku`). Such an override with no
`tools:` line inherits every tool, including `Write`. The resolver returns
`False` from the built-in table before looking at `.claude/agents/`. It fails
towards READ-ONLY, not towards "unknown, keep today's behaviour" which the
module's own contract promises for anything it cannot be sure of. Line 241 of
the same doc also gives managed agents precedence over project/user ones;
those are not consulted.

**Failure scenario** (probe P7): a project defines
`.claude/agents/explore.md` with `name: Explore` and `tools: Read, Write, Bash`.
An oversized stop whose persistence failed gets the condense message and "has
no `Write` tool"; `dispatch_declaration` advises the coordinator that an agent
which CAN write cannot.

**Suggested fix**: Resolve project agents, then user agents, then the built-in
table. Either consult the managed settings `agents/` directory or document that
a managed override is out of scope. Add a test for a project `Explore` override
with and without a `tools` line.

---

## Minor

### m1. `find_persisted_report` picks the OLDEST file on a collision, not the newest (Confidence 90%)
**Location**: `utils/subagent_report_paths.py:151-167`. Lexicographic sort puts
`...-abc123-2.md` before `...-abc123.md` (`-` is 0x2d, `.` is 0x2e) and `-10`
before `-2`. Probe P5 returns the unsuffixed original. **Fix**: sort by
`(stat().st_mtime, name)` or parse the suffix number; add a test with an
original plus `-2` and `-10`.

### m2. The size blocker can cite an EARLIER stop's file for the same agent_id (Confidence 75%)
**Location**: `subagent_report_size_blocker.py` `_find_persisted_report` plus
`handle` ordering. Resumed agents keep their `agent_id`. If this stop's write
failed (disk full, permissions), the glob still finds the previous stop's file
and the deny says "The full text is already saved at" a file that holds an
older reply (probe P8). **Fix**: only cite a match whose content equals the
current `last_assistant_message` (or whose size matches and mtime is within a
few seconds); otherwise fall back to the existing messages.

### m3. `write_new_file_never_overwrite` leaves a truncated file behind when the content write fails (Confidence 80%)
**Location**: `utils/subagent_report_paths.py:121-126`. After `os.open` with
O_EXCL succeeds, an `OSError` from `handle.write` returns None but leaves an
empty or partial file, which `find_persisted_report` will later cite (m2) and
which counts against retention. **Fix**: on write failure, `candidate.unlink()`
(log if that fails too), then return None; add a test that forces the write to
fail (monkeypatch `os.fdopen`).

### m4. The read-only dispatch advisory fires on any plan-folder mention, not on a declared report path (Confidence 80%)
**Location**: `dispatch_declaration.py` `_read_only_dispatch_mismatch` (reuses
`_has_declaration`). `_has_declaration` is true for any `CLAUDE/Plan/NNNNN-`
path. Dispatching `Explore` or `code-reviewer` with "context: read
CLAUDE/Plan/00460-x/PLAN.md" produces "this prompt declares a report
destination. It cannot write a report file there", which is false. Task 1.4
scoped this to a declared REPORT PATH. It also calls `_has_declaration` a
second time after `handle` already did. **Fix**: gate the advisory on
`_DESTINATION_PATTERN` (a write/save/report verb followed by a path) and pass
the already-computed result in, rather than re-evaluating; add a negative test
for a read-only dispatch that only cites a plan folder as context.

### m5. Root-resolution logic is duplicated, and the shared helper lives in the wrong module (Confidence 85%)
**Location**: `subagent_report_persistence.py:104-119` duplicates
`subagent_tool_resolution.resolve_lookup_root` (lines 171-189) line for line;
`subagent_report_path_verifier.py:137-146` and
`cron_subagent_stop_enforcer.py:76` carry their own variants. A project-root
fallback chain has nothing to do with tool resolution. **Fix**: move
`resolve_lookup_root` next to `resolve_project_root` in `utils/path_exclusion.py`
(or a handler-base helper) and call it from all four handlers.

### m6. Two knobs, one directory: the size blocker's lookup dir and fallback dir are not tied to the persister's `report_dir` (Confidence 80%)
**Location**: `subagent_report_size_blocker.py:54` still hard-codes
`"untracked/agent-reports/"` (`dispatch_declaration` was switched to
`DEFAULT_REPORT_DIR`; the blocker was not); `_persisted_report_dir` is a
separate option that must be changed by hand in step with the persister's
`report_dir`. The example config documents only the persister's option, so an
operator who follows it silently loses the "already saved" message. **Fix**:
import `DEFAULT_REPORT_DIR` for the fallback constant; make the blocker read
one shared setting (for example a `subagent_stop`-level option or reading the
persister's configured value), or at minimum document `persisted_report_dir`
beside `report_dir` in the example config.

### m7. Docs and release note overstate the guarantees (Confidence 85%)
**Location**: persistence docstring line 17 cites `test_report_dir_is_gitignored`,
which does not exist (the real test is `test_is_actually_gitignored_in_this_repo`,
and it covers this repo only). `get_claude_md()` (lines 168-184) and release
note `CLAUDE/UPGRADES/UNRELEASED/release-notes/10-*.md` lines 14-20 say
"gitignored file" unconditionally (false in clients, B1). The release note does
not tell operators that `untracked/agent-reports/` is now pruned (B2) or that
persisted content is not content-checked. The CLAUDE.md one-liner for the size
blocker still reads "write large reports to a file". **Fix**: correct the test
name; state the gitignore condition (or make it true via B1); add an operator
line about pruning and the dedicated subdirectory; update the size-blocker
one-liner.

### m8. Persisted replies are created 0644 (Confidence 70%)
**Location**: `utils/subagent_report_paths.py:60`. Replies can contain
sensitive material; the existing agent-authored reports in that directory are
0600, and `retention.cap_log_file` goes out of its way to preserve owner-only
modes (Plan 00239). **Fix**: `_FILE_MODE = 0o600`; create the directory 0o700.

### m9. TDD theatre: the persister's acceptance-test producibility test never executes its body (Confidence 95%)
**Location**: `tests/unit/handlers/subagent_stop/test_subagent_report_persistence.py:229-243`.
It filters for `TestType.BLOCKING`, but the handler declares a single
`TestType.ADVISORY` acceptance test, so the loop runs zero times and the test
passes whatever the handler does. **Fix**: drive the ADVISORY test's
`hook_input` against a handler rooted at `tmp_path` and assert ALLOW plus
exactly one file containing the message; assert the collected list is non-empty.

### m10. Handler-level tests are not hermetic (Confidence 75%)
**Location**: `test_subagent_report_size_blocker.py` (every test that does not
set `_project_root`, e.g. `TestReadOnlyAgent.test_unresolvable_agent_type_behaviour_unchanged`)
and `test_dispatch_declaration.py` equivalents. These resolve against the real
checkout (globbing its real `untracked/agent-reports/`) and the real
`Path.home()/.claude/agents`, because handlers never pass `home_dir`. The
resolver docstring claims tests never touch the real home. After merge, the
main checkout's agent-reports directory is live, so the result of a fallback
test depends on what the dogfooded daemon has written there. **Fix**: an
autouse fixture that sets `_project_root = tmp_path` and monkeypatches
`Path.home` (or add a `_home_dir` test seam alongside `_project_root`).

### m11. `_find_agent_frontmatter` swallows `OSError` without logging (Confidence 70%)
**Location**: `utils/subagent_tool_resolution.py:130-133`. Every other fail-open
site added by this plan logs; this one is a bare `continue`, which the
exclusion entry justifies but the project rule ("log them") still asks for.
An unreadable agent file silently changes the resolver's answer to "unknown".
**Fix**: `logger.debug("cannot read agent file %s: %s", path, exc)` before
`continue`.

---

## Checked and found sound

- **Path traversal via agent_type/agent_id**: `_SAFE_COMPONENT_RE` maps
  everything outside `[A-Za-z0-9._-]` to `_`, so `/` can never appear; `..`
  can survive but only as part of a single filename behind the timestamp
  prefix. Glob metacharacters (`[`, `*`, `?`) are also mapped, so
  `find_persisted_report`'s pattern cannot be widened by a crafted type.
- **Symlink at the file**: `O_CREAT | O_EXCL` refuses an existing symlink,
  dangling or not, so a planted link cannot redirect the write. A symlinked
  report DIRECTORY is followed, but planting that already requires write
  access to the working tree. Prune unlinks symlinks rather than their
  targets.
- **Concurrency**: distinct agents get distinct filenames; O_EXCL makes
  same-name races safe. Two overlapping prunes can race on one unlink and log
  a spurious WARNING, which is harmless.
- **Never blocks**: non-terminal, every path returns ALLOW, IO errors logged;
  the chain fails open on an unexpected exception in non-strict mode. Per-stop
  cost is one write plus one stat pass over at most the retention cap.
- **Resolver semantics**: `tools` absent means inherit; `disallowedTools`
  subtraction matches the documented order; specifier stripping; name-not-
  filename matching; recursive scan; malformed field resolves to None; this
  project's `code-reviewer`, `security-reviewer`, `hooks-daemon-docs-qa`,
  `qa-runner`, `transcript-inspector` and `plan-dedupe-scout` all resolve
  read-only as intended. Unknown and plugin types resolve to None and keep
  pre-plan behaviour, as specified (M4 is the one exception).
- Task 1.2's evidence-based decision, the vendored citations, and the
  explicit Bash-workaround prohibition in the read-only message are good work.
