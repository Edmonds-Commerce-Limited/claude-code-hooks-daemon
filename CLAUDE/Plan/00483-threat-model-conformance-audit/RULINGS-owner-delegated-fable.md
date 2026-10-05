# Rulings on N230, N154, N240

Decisions delegated by the owner to a Fable subagent, 2026-10-02.

Governing ruling: `CLAUDE/ARCHITECTURE.md` § "Threat model: the agent is careless, not hostile"
(lines 783-864). Each entry below was decided against that section: the two-part out-of-scope
test (819-832), the false-positive clause (840-843), and the "What this ruling does not change"
block (845-861), in particular the no-escape-hatch rule (851-852) and the human-gated steps,
protected-path disclosure among them (853-854). Every code citation was read on `main` at
`4988db01d`; nothing was taken from the branch write-ups without checking it.

| Entry | Ruling    | One line                                                                                                          |
| ----- | --------- | ----------------------------------------------------------------------------------------------------------------- |
| N230  | FIX       | `allow_plain_hash` is honoured only from the config of the project that CONTAINS the inspected file               |
| N154  | FIX       | `run_git`/`read_blobs` drop `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR` from the child env     |
| N240  | NO CHANGE | an out-of-root `script` log is not a protected outcome; pin both shapes in the corpus as `UNCOVERED-accepted`     |
| N55   | FIX       | an absent config block defers to the handler's declared default; the 11 opt-in handlers stay off until named      |
| N62   | NO CHANGE | subagent context/concurrency budgets stay with the harness knob and the Plan 00479 ceiling; re-open trigger named |
| N74   | NO CHANGE | `grep -r` over an ancestor stays an accepted, precisely documented residual; denying it denies every `grep -r .`  |
| N96   | FIX       | split `subagent_full_qa_blocker.py` along its class seams as a pure-refactor plan, sequenced after open branches  |

The second group (N55, N62, N74, N96) was added under the same delegation, extended to these
four by the coordinator rather than named by the owner directly; the owner may overrule any of
them.

**Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** N55, N62 and N96
are confirmed (resolved). N74 is decided together with R4 (see the plan's open question 4), because the review's R7
proposes resolving it through R4's cached index. Not owner rulings.

---

## N230 — `secret-meta --project-root <dir>` reads `allow_plain_hash` from a config the agent wrote

### Question

May `hooks-daemon secret-meta --project-root DIR` take `allow_plain_hash` (the option that
turns the bucketed size and keyed digest into an exact byte count and a plain sha256) from a
config file at `DIR/.claude/hooks-daemon.yaml` that the agent wrote itself?

### Evidence

- `src/claude_code_hooks_daemon/daemon/cli.py:6555-6566` — `cmd_secret_meta` takes
  `args.project_root` "trusted as-is", loads `load_config_safe(project_root)` and reads
  `allow_plain_hash` from it. `daemon/validation.py:139` shows that is simply
  `<project_root>/.claude/hooks-daemon.yaml`.
- `cli.py:6544-6546` (docstring) and `docs/guides/HANDLER_REFERENCE.md:1972` both claim
  "there is no CLI override, so an agent cannot self-grant the plainer disclosure". The code
  contradicts its own documentation: `--project-root` IS the override.
- `cli.py:11382-11386` — the flag's help text: "trusted as-is; auto-detected by default".
- `bin/hooks-daemon:45-48, 319-322` — the wrapper passes its own derived root as
  `--project-root` FIRST; a caller's `--project-root` is appended after it and argparse takes
  the last, so the caller always wins. The CLI cannot tell the wrapper's value from the
  caller's.
- `src/claude_code_hooks_daemon/utils/secret_file_matching.py:2597-2598` — the
  `secret_file_guard` exemption is `head basename == hooks-daemon and words[1] == secret-meta`;
  every later word is unexamined, so
  `bin/hooks-daemon secret-meta <protected> --project-root untracked/scratch/x` is exempt.
- `project_containment` denies a write to `/tmp`, but `untracked/scratch/x/.claude/hooks-daemon.yaml`
  is inside the repository and gitignored: writable, exempt from review, invisible in any diff.
- `tests/unit/daemon/test_cli_secret_meta.py:38-56` — the existing test grants the plain hash
  from a config in the SAME `tmp_path` that holds the file; no test covers a config elsewhere.
- `utils/secret_meta.py:8-16` — why the plain fields are withheld by default: exact length and
  an unkeyed hash of a low-entropy secret are an offline-crackable commitment once in a
  transcript.

### Ruling: FIX

### Reasoning

This is not settled by the two-part test — the shape is literal, visible, and `--project-root`
has a working purpose — so the "What this ruling does not change" block decides it, and two of
its bullets apply directly:

1. **Protected-path disclosure is a human-gated step** (853-854). `allow_plain_hash` is the
   project owner's decision, recorded in the tracked `.claude/hooks-daemon.yaml`
   (`git ls-files` confirms it is tracked). A config under `untracked/scratch/` is nobody's
   decision and never reaches a reviewer.
2. **No guard gains an escape hatch an agent can type** (851-852), and "an agent talking itself
   into an exception is the careless agent, not the hostile one". The route here is exactly
   that: a block reason says "use `secret-meta`", the docs say the exact hash needs
   `allow_plain_hash`, the agent reasons "I'll make a config that sets it". Three ordinary tool
   calls, each individually allowed.

Plausibility: moderate rather than everyday, but the owner's text has already decided that
self-granting counts as careless, so the tiebreaker is not needed.

False-positive cost of the fix: none that I can find. The wrapper anchors the root for every
normal call, so `--project-root` on `secret-meta` is only ever a human's cross-project probe;
under the fix that probe still answers (existence, bucket, mtime, mode, digest), it merely
withholds the two plain fields unless the file's OWN project grants them — which is the right
owner of that decision anyway.

What this does NOT close, and deliberately: an agent may still edit the tracked
`.claude/hooks-daemon.yaml` to set `allow_plain_hash: true`. Every block message in this project
prints "To disable: handlers.pre_tool_use.X (set enabled: false)", so agent-editable
configuration is the accepted model, and that edit is visible in the working tree and in every
diff. The defect in N230 is the INVISIBLE grant, not the visible one. The docstring and the
reference row should stop claiming "an agent cannot self-grant" and say what is true: the grant
comes from the tracked config of the project that owns the file.

Why not the branch's remedy ("config and key from `get_project_path(None)`")? That is a CWD
walk-up, which `bin/hooks-daemon:50-55` forbids as an input ("CWD IS NEVER AN INPUT"), and the
wrapper's own `--project-root` is indistinguishable from a caller's, so it cannot be used as the
anchor either without a wrapper change. The containment rule below needs neither.

### Implementation brief

Behaviour: `allow_plain_hash` is honoured only when the inspected path, fully resolved, lies
inside `project_root`, fully resolved. Everything else about `--project-root` is unchanged: it
still names where the config and the HMAC key live.

1. `cli.py` `cmd_secret_meta`, after line 6566:

   ```python
   target = Path(args.path).resolve()
   root = project_root.resolve()
   if allow_plain_hash and not target.is_relative_to(root):
       allow_plain_hash = False
   ```

   (`Path.is_relative_to` is 3.9+; the project already uses `utils.path_containment.path_relative_to`
   if a shared helper is preferred.) Resolve both sides so a symlink under a scratch root that
   points at a protected file elsewhere is placed where it really is.

2. Rewrite the docstring at `cli.py:6544-6546`: "Exact size and plain sha256 appear only when
   the `secret_file_guard` `allow_plain_hash` option is true IN THE CONFIG OF THE PROJECT THAT
   CONTAINS THE FILE. A `--project-root` elsewhere never grants it: that root's config is not
   the file owner's decision." Replace the `--project-root` help at 11385 with "Project root for
   config + key resolution (auto-detected by default; grants the plain hash only for files
   inside it)". Update `docs/guides/HANDLER_REFERENCE.md:1972` to the same truth and drop
   "an agent cannot self-grant it".

3. Tests, `tests/unit/daemon/test_cli_secret_meta.py`:

   - `test_a_config_outside_the_files_project_never_grants_the_plain_hash`: `grant_root = tmp_path / "scratch"` with `.claude/hooks-daemon.yaml` setting `allow_plain_hash: true`;
     `secret = tmp_path / "fixture.vault-password"` (NOT under `grant_root`); run with
     `project_root=grant_root`; assert `"size_bucket" in meta`, `"sha256" not in meta`,
     `"size_bytes" not in meta`, and `meta["exists"] is True` (the default disclosure still
     answers). RED on main.
   - `test_a_symlink_under_the_granting_root_is_placed_where_it_points`: same, with
     `grant_root / "link.vault-password"` symlinked to the outside secret; assert no plain
     fields. RED on main.
   - The existing `test_plain_hash_requires_config_option` stays GREEN (file inside the root).

4. No change to `secret_file_matching.py`: the exemption shape is the sanctioned helper and
   must stay a single-command exemption; the fix lives where the grant is decided.

---

## N154 — `run_git` passes an inherited `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` through

### Question

Should the daemon's single git spawn point strip relocating `GIT_*` variables that arrive in the
daemon's own environment (or in a caller-supplied `env`), so every probe answers for the
repository named by `-C <cwd>`?

### Evidence

- `src/claude_code_hooks_daemon/utils/git_repo.py:134` — `child_env = {**os.environ, **(env or {}), GIT_OPTIONAL_LOCKS: "0"}`.
  Nothing removes `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` or `GIT_COMMON_DIR`; any of
  them overrides `-C <cwd>` for the repository, work tree or index git reads.
- `git_repo.py:168` — `read_blobs` builds the same environment a second time, inline. Any fix
  to `run_git` alone leaves the batch blob reader (used by the commit gates) inconsistent.
- `git_repo.py:103-115, 126-133` — the docstring's own argument: the runner exists so that
  properties "hold by construction rather than per call site", and the declined lock is applied
  last precisely because "a caller that passes a whole `os.environ` copy would otherwise
  reinstate an inherited" value. `utils/git_sync.py:116,119` (`_noninteractive_env`) is that
  caller.
- `utils/git_invocation_directory.py:22-25` — the daemon already holds that these four
  variables "point git at a repository, work tree or index other than the one its directory
  names", and `placement_problem` makes every gate DENY an agent's git command that sets one,
  because it "must deny rather than judge the wrong repository". The daemon applies a standard
  to the agent's git that it does not apply to its own.
- `cli.py:806-809` — daemonisation changes cwd to `/` and the session, but keeps the
  environment it was started with for the daemon's whole life.
- Routes by which the variables reach that environment: the daemon is started by `ensure_daemon`
  from the hook forwarder (`.claude/hooks/pre-tool-use:35`), i.e. with Claude Code's own
  environment — so a `claude` launched from inside a git hook, `git bisect run` or
  `git rebase -x`, or a shell that exports `GIT_DIR` (the bare-repo dotfiles pattern), carries
  them in. No shipped git hook invokes the CLI (`core.hooksPath` is unset here, `.git/hooks`
  holds only samples, and `handlers/post_tool_use/git_hooks_executable_fixer.py` only fixes
  permission bits), so there is no case where an inherited `GIT_INDEX_FILE` is INTENDED.
- Existing tests: `tests/unit/utils/test_git_repo.py:355-397` (`TestCallerSuppliedEnvironment`)
  already pin the merge-and-override behaviour with a mocked `subprocess.run`; the new tests
  slot in beside them.

### Ruling: FIX

### Reasoning

This is not a threat-model entry at all, and I would record it as such: the two-part test is
about shapes the agent types, and no agent-typed shape is involved (an agent typing
`GIT_DIR=… bin/hooks-daemon restart` is literal and in scope but not something a careless agent
does). It is a self-consistency defect in the daemon: every call site passes `-C <cwd>` and asks
about THAT repository; an inherited relocating variable silently makes every answer — the staged
tree a commit gate scans, the branch a merge gate checks, the hooks directory the fixer chmods —
come from a different repository or index, with no error and no failing test. Rare trigger;
silent wrong answers when it fires; cheap to close.

False-positive cost: zero. There is no daemon path that wants a relocated repository (the grep
above found none), and a caller that needed one would pass `--git-dir` as an argument, which
nothing stops. Human gates and the no-escape-hatch rule are untouched.

### Implementation brief

1. `git_repo.py`: add

   ```python
   #: Each of these points git at a repository, work tree or index other than
   #: the one ``-C <cwd>`` names. Shared with ``git_invocation_directory``.
   RELOCATING_VARIABLES: Final[frozenset[str]] = frozenset(
       {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
   )

   def _child_environment(env: Mapping[str, str] | None) -> dict[str, str]:
       merged = {**os.environ, **(env or {})}
       for name in RELOCATING_VARIABLES:
           merged.pop(name, None)
       merged[_OPTIONAL_LOCKS_VAR] = _OPTIONAL_LOCKS_DECLINED
       return merged
   ```

   Use it at both line 134 (`run_git`) and line 168 (`read_blobs`). Remove after merging the
   caller's env, so a whole-`os.environ` copy cannot bring a variable back.

2. `git_invocation_directory.py:22-24`: import `RELOCATING_VARIABLES` from `git_repo` instead of
   redefining it (same-fact-one-home; the repo's own idiom, `git_repo.py:60`). Check the import
   direction is acyclic (`git_repo` must not import `git_invocation_directory`; today it does not).

3. Tests, `tests/unit/utils/test_git_repo.py`, new class `TestARelocatedRepositoryIsNotInherited`:

   - mocked `subprocess.run`, `mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere/.git"})`:
     `"GIT_DIR" not in runner.call_args.kwargs["env"]`, and `GIT_OPTIONAL_LOCKS == "0"` still.
   - mocked, caller `env={"GIT_INDEX_FILE": "/elsewhere/index"}`: absent from the passed env
     (the whole-copy case, mirroring `test_a_caller_cannot_re_enable_the_optional_lock`).
   - real repositories: create `repo_a` and `repo_b`; under
     `mock.patch.dict(os.environ, {"GIT_DIR": str(repo_b / ".git")})`,
     `run_git(repo_a, "rev-parse", "--show-toplevel").stdout.strip()` resolves to `repo_a`.
     Add the control the file already uses for the lock
     (`test_the_control_shows_bare_git_would_have_rewritten_it` pattern): bare
     `subprocess.run(["git", "-C", repo_a, "rev-parse", "--show-toplevel"], env=…)` answers
     `repo_b`, proving the variable would have relocated it.
   - `read_blobs` with mocked `subprocess.run` under the same patched environ: `"GIT_DIR"`
     absent from the passed env.
     All RED on main except the lock assertion.

4. Release note (one line) and the N154 row in the ledger: "Fixed on main; classified as a
   daemon self-consistency defect, not a threat-model entry".

---

## N240 — `bash_file_writes` does not report the typescript or the `-I`/`-O`/`-B`/`-T` log files `script` writes

### Question

Should an out-of-root log written by `script` (`script -q /tmp/typescript.log -c ls`,
`script -O /tmp/out.log`) be guarded — by `project_containment` for the location, or by the
`bash_file_writes` consumers (`plan_journal_guard`, `upgrade_approval_guard`) for the target?

### Evidence

- `src/claude_code_hooks_daemon/handlers/utils/bash_file_writes.py` (whole module) and
  `core/utils.py` — no `script` anywhere; the triage probe confirms both shapes are allowed.
- `handlers/pre_tool_use/project_containment.py:13-15` — the harm it guards is DURABILITY:
  "anything written there is lost on restart, invisible to git and outside review".
  Lines 23-31 declare the boundary: "Named targets only … it cannot see a library's temp file
  and must not pretend to"; lines 113-128 show the extension model is per-command tables
  (`curl -o`, `wget -O`, `rsync`/`scp`, `mkdir`) added for commands agents actually type.
- `tests/CLAUDE.md` (in-tree instruction, bottom of the file): `project_containment` "denies an
  ordinary redirect outside the repository, but not a path passed to a script as a plain
  argument — a backstop, not a guarantee." The `script` operand is a path passed as a plain
  argument; the gap is the documented one.
- `bash_file_writes.py:1-28` — its consumers hold specific files against hand-written changes:
  a plan `JOURNAL/` day-file (`plan_journal_guard`) and an approval marker
  (`upgrade_approval_guard`). `install/upgrade_gate.py:368-379` — an approval marker is read
  back as JSON and must carry the expected fields; a `script` typescript cannot satisfy that.
- `ARCHITECTURE.md:802-804` — the protected outcomes: uncommitted work, protected file
  contents, what reaches GitHub, repository history, the system Python.

### Ruling: NO CHANGE

Record both probe shapes in `scripts/qa/dangerous-invocation-corpus.yaml` with verdict
`UNCOVERED-accepted` (format at lines 15-17 and the `history-rebase` row) so the next sweep does
not raise them again, and mark the ledger row "No change (not a protected outcome)" rather than
"Dismissed (threat model)" — neither limb of the two-part test applies and the entry should not
claim one does.

### Reasoning

The two-part test does not dismiss this: the shape is literal and `script` has a working purpose.
So the question is the one the ruling asks next — is the OUTCOME one the daemon protects, and
what do a miss and a false positive each cost?

- **The outcome is not lost work.** `script` writes a copy of what it is simultaneously showing on
  the terminal. The agent has already seen every byte the typescript holds, so a `/tmp` log wiped
  on restart loses nothing the agent did not have. That is the exact opposite of
  `pytest > /tmp/out.txt`, where the redirect is the ONLY copy, which is why containment denies
  the redirect. A log that duplicates the terminal is not "uncommitted work" in the ruling's sense.
- **The miss is cheap; the false positive is not.** The one `script` idiom a careless agent does
  reach for is the pty wrapper, `script -qc "<tui>" /dev/null` (also `script -q /dev/null -c …`),
  whose operand is the null device and which a parser would have to special-case; `script` with
  no operand writes `./typescript` INTO the repo, which is litter but not containment's concern;
  and the `-I/-O/-B/-T` flags are rare. A per-command table for `script` would mostly be
  exercised by the `/dev/null` case, and a wrong denial of a pty wrapper costs an agent the only
  route it has to drive a TUI. Clause 840-843 settles that trade.
- **No human gate is touched.** Using `script` to write a JOURNAL day-file or an
  `upgrade-approvals/` marker has no working purpose other than defeating the parser (limb 2),
  and the marker must parse as JSON with the expected fields, so a typescript grants nothing.
  Those guards "keep the shapes they already close" (853-854); `script` was never one of them.
- **It is the documented boundary.** `tests/CLAUDE.md` tells agents the plain-argument gap exists
  and that containment is "a backstop, not a guarantee". Closing one plain-argument command and
  not the hundreds of others (`cp` is covered; `ffmpeg out.mp4`, `tar -cf /tmp/x.tar`,
  `sqlite3 /tmp/db` are not) would make the boundary less honest, not more.

If a future sweep shows agents actually writing typescript logs to `/tmp` in ordinary work, the
right shape of fix is a `script` entry in `project_containment`'s command tables (positional
operand plus `-O/--log-out`, `-I/--log-in`, `-B/--log-io`, `-T/--log-timing`, null device
excluded), not a `bash_file_writes` extension. Nothing seen so far justifies building it.

---

## N55 — `register_all` ignores `get_default_enabled()` when the config block is absent

### Question

When a handler has no block under `handlers.<event>` in `.claude/hooks-daemon.yaml`, which
source decides whether it runs: the handler's own `get_default_enabled()` (so opt-in handlers
stay off), or the registry's "absent means enabled", with the docs and `init minimal` changed to
say so?

### Evidence

- `src/claude_code_hooks_daemon/handlers/registry.py:226-241` — `config_skip_reason` documents
  "Absent means ENABLED — registration defaults `enabled` to True — and so does `None`". Line
  237 is `block.get(ConfigKey.ENABLED, True)`. `get_default_enabled` is not consulted anywhere
  in the registry (only `config_skip_reason` at 291 and 656). Line 651
  (`event_config.get(config_key) or {}`) erases the difference between an absent key and a
  bare `key:`.
- `src/claude_code_hooks_daemon/core/handler.py:385-407` — the base method's contract:
  "`False` = opt-in (off unless the client explicitly enables it)". It is the "single source of
  truth for a handler's semantic default enabled state"; the full config template carries a
  matching `enabled: false` literal and a drift test keeps the two sets equal. Nothing keeps
  the REGISTRY equal to either.
- Eleven handlers return `False`: `compaction_signal`, `goal_injection`,
  `quarantine_artefact_read_guard`, `subagent_full_qa_blocker`, `context_sidecar`,
  `flaggable_work_advisor`, `session_actions_directive`, `flaggable_content_channel_guard`,
  `skill_opportunity_detector`, `tool_disable_advisor`, `host_hostname`. Their docstrings say
  "Opt-in", "ships dormant", "only useful when a supervisor is …". Three of them DENY tools.
- `src/claude_code_hooks_daemon/daemon/init_config.py:65-100` — `init minimal` emits
  `pre_tool_use: {}` and the same for every event, so on a minimal install all eleven run.
- `docs/guides/HANDLER_REFERENCE.md:3337` — the goal-flip branch already documented the
  contradiction for `goal_injection` ("registration does not consult that default for an
  ABSENT block … set `enabled: false` explicitly to keep it off"), which is a doc describing a
  defect rather than a design.
- `CLAUDE/HANDLER_DEVELOPMENT.md:1198-1203` — the stated split: `get_default_enabled()` answers
  "safe without knowing the project"; `get_relevance()` answers "worth it, knowing the
  project". A guard that is NOT safe without knowing the project is exactly what the
  opt-in default exists to keep off.
- This project's own `.claude/hooks-daemon.yaml` names all eleven, so the fix changes nothing
  for the dogfood install.

### Ruling: FIX — the handler's declared default decides an absent block

### Reasoning

Not a threat-model question; a false-positive and truthfulness question, and the ruling's
clause 840-843 points the same way. A handler is opt-in because it is wrong to run without a
precondition the project may lack (a ccy supervisor, a deployed quarantine agent, a host
hostname) or because it denies tool calls that are only right under a coordinator discipline
(`subagent_full_qa_blocker`, `flaggable_content_channel_guard`,
`quarantine_artefact_read_guard`). On a minimal install every one of those runs with no
precondition, which is a denial or an advisory the project never asked for — a false positive
by construction. The alternative, "absent means enabled stands", leaves a method named
`get_default_enabled` whose answer is consulted by the template generator and the upgrade
advisory but never by the thing that enables handlers, and eleven docstrings that describe a
state the daemon does not implement. Making the code match the eleven docstrings is cheaper and
more honest than rewriting eleven docstrings and a reference page to match one `True` literal.

Cost of the change: a client whose hand-written or `init minimal` config omits an opt-in
handler and relies on it running today loses it on upgrade. That is a truth change and must be
recorded as one (`CLAUDE/UPGRADES/` truth-changes manifest, release note, and the
config-changes advisory already "consumes this method directly", so it can name the eleven).
`init full` installs are unaffected: the template carries `enabled: false` for each.

### Implementation brief

1. `core/handler.py`: add a class attribute `default_enabled: ClassVar[bool] = True` and have
   the base `get_default_enabled()` return `type(self).default_enabled`. The eleven opt-in
   handlers set `default_enabled = False` at class level (their method overrides can go, or stay
   returning the attribute). This gives the registry a pre-construction answer without running
   a constructor, which `config_skip_reason`'s own docstring forbids (222-223).
2. `handlers/registry.py`: `config_skip_reason(handler_config, *, registry_disabled, default_enabled: bool = True, present: bool = True)`. Rule: a block that is PRESENT (a
   mapping, or a bare `key:` parsing to `None`) is enabled unless `enabled: false` — mentioning
   the handler is opting in; a block that is ABSENT is enabled iff `default_enabled`. Return
   `"off by default and not configured"` for the new skip. At line 651 keep
   `present = config_key in event_config` before the `or {}`; pass `attr.default_enabled`.
   `would_register` (282-293) and the project-handler path get the same two arguments so the
   checklist cannot disagree with dispatch.
3. Docs: rewrite `registry.py:226-228`, `HANDLER_REFERENCE.md:3337`, and add one sentence to
   `HANDLER_DEVELOPMENT.md` beside line 1199: "an absent block defers to this default; a present
   block is enabled unless it says otherwise". Record the truth change.
4. Tests (`tests/unit/handlers/test_registry*.py`), RED on main:
   - an opt-in handler with no block is not registered; with a bare `key:` it is; with
     `enabled: true` it is;
   - an opt-out handler with no block is still registered (pins today's behaviour for the
     majority);
   - `would_register` agrees with `register_all` for both defaults (the checklist contract);
   - a drift test: the set of handlers with `default_enabled = False` equals the set whose
     `get_default_enabled()` is `False` (keeps the existing template drift test meaningful).

---

## N62 — Nothing bounds a subagent's context, so long-lived agents burn the usage budget

### Question

Should the daemon enforce subagent context and concurrency budgets (a transcript-size budget
that advises then denies, a resume guard on `SendMessage` to a stopped agent, a cap on `Agent`),
or leave this to `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the Plan 00479 usage pause?

### Evidence

- `CLAUDE/Plan/Completed/00466-niggles-ledger-sixteen/NIGGLES.md:1834-1862` — the owner's
  measurements (584 transcripts, compaction at about 570k tokens, a 2,374-message resume) and
  the four candidate remedies.
- `CLAUDE/Plan/00479-subscription-usage-monitor-and-ceiling/PLAN.md:123-128` (Task 4.2, merged
  `506fd3f5e`): at the host ceiling the session pauses, running subagents finish, `Agent`/`Task`
  are denied so no new ones start, and a subagent over the ceiling also starts the pause.
  Phase 4.8 live acceptance is in progress (`subagent-reports/261002-p479-acceptance-sonnet.md`).
- The harm in N62 is the subscription window being exhausted. That is precisely the outcome
  00479 now bounds, by measuring the thing itself (usage) rather than a proxy for it (context
  size × tool calls × agents).

### Ruling: NO CHANGE (for now), with a named re-open trigger

### Reasoning

Not a threat-model entry — no protected outcome and no agent shape — so it is weighed purely on
cost and benefit. The daemon's version of a context budget would read every subagent's
transcript on every PreToolUse to find the latest usage figure, which is a per-call file read
over a growing file, on the hook path; its deny mode ("only the report file and the coordinator
message") is a second pause mechanism beside 00479's, with its own lifecycle, exemptions and
stop-hook interactions to get right. The proxy it enforces is one the harness already exposes
as a single knob (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`), and the outcome it protects is one 00479
already measures directly. Building it now would duplicate both before 00479's acceptance data
says whether the ceiling alone is enough.

Re-open trigger, so this is a decision and not a shelving: if 00479's acceptance or the first
weeks of use show the pause firing routinely because of subagent context rather than genuine
work volume, build the CONCURRENCY CAP first — deny `Agent` above a configured running-teammate
count. It is deterministic, needs no transcript reads, and attacks the multiplier in the
owner's own cost formula. The transcript-reading budget and the resume guard stay unbuilt unless
the cap proves insufficient. Record N62 as "No change; re-open on the 00479 trigger".

---

## N74 — A recursive grep over a protected directory is allowed

### Question

Is a Bash recursive content search rooted at an ancestor of a protected path (`grep -r '' .`,
`rg -uu '' .`) an accepted, documented residual, given that denying it denies every
`grep -r pattern .` in a repository that holds a protected file? Weighed against the ruling's
"a protected file stays protected against every ORDINARY read route, including `Grep -l` and
an interpreter one-liner" (855-856).

### Evidence

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:1763-1779` — the
  handler's own "Honest limits" text lists "a Bash recursive content search rooted at an
  ancestor directory (`grep -r`/`rg` over a tree containing the file)" as NOT covered, and
  states the policy: "An unblocked evasion is NOT permission".
- `secret_file_guard.py:1466-1477` — the `Grep` TOOL rooted at a directory IS judged, by a
  bounded walk (`directory_contains_protected`), and denied when the tree holds a protected
  file. The Bash spelling has no counterpart.
- `utils/secret_file_matching.py:77-82` — the shipped protected globs are file NAMES
  (`*.secret*`, `.vault-pass*`, `id_rsa`, …), not directories. The two protected files this
  project actually holds are `.claude/block-words.secret` (gitignored) and the HMAC key under
  `untracked/` (gitignored). `rg` skips gitignored and hidden files by default, so only
  `rg -uu` / `--hidden --no-ignore` reaches them; GNU `grep -r` reads both.
- `ARCHITECTURE.md:840-843` — "If catching an out-of-scope shape costs an in-scope false
  positive, let the shape through."

### Ruling: NO CHANGE — accepted residual, documented more precisely

### Reasoning

The two-part test does not dismiss this (literal shape, working purpose), so the question is
the clash between two bullets of the same ruling. The "ordinary read route" bullet protects
routes aimed AT the file: every example it gives (`cat`, `grep` with the path, `find -exec`, an
interpreter one-liner, `Grep -l`) names the protected path or discovers it by walking to it. A
recursive search rooted at `.` names nothing and reads everything; the only thing the daemon
could key on is that the tree CONTAINS a protected file, which in this repository is always.
Denying on that would deny `grep -rn "def foo" .` in every project that has a word list — the
single most common search an agent types — and clause 840-843 settles that trade explicitly.
The residual is also bounded in a way the ledger did not weigh: a pattern search discloses only
lines matching a pattern the agent already holds, and `rg`, the search most agents reach for,
skips both of this project's protected files unless told not to.

The Grep-tool asymmetry (1466-1477) is noted, not extended. That walk denies the Grep tool
rooted at any ancestor within its cap; if that cap reaches the repository root, the Grep tool is
ALREADY an everyday denial here, which would explain why agents use Bash `rg` instead. That is
worth one measurement in its own right before anyone copies the rule to Bash; it is not a
reason to copy it.

A narrower fix was considered and declined: denying only a catch-all dump (`grep -r ''`,
`grep -r .`, `rg -uu ''`) over an ancestor. `grep -rc ''` and `grep -rl ''` are legitimate
(line counts, non-empty files), a careless agent wanting content types `cat` not an empty
pattern, and the shape is rare enough that the corpus row is the right record.

Actions: keep the "Honest limits" text, and make the reference row say the residual precisely —
"a recursive content search rooted above a protected file (`grep -r`, `rg -uu`) is not denied;
`rg` skips gitignored and hidden files by default, GNU `grep -r` does not; OS-level controls
(a separate user, encryption at rest) are the guarantee" — and add two corpus rows,
`grep -r '' .` and `rg -uu '' .`, verdict `UNCOVERED-accepted`, so the next sweep stops raising
it. Ledger row: "No change (accepted residual; false-positive clause)".

---

## N96 — `subagent_full_qa_blocker.py` is one 5,301-line handler

### Question

Refactor the module now, or accept its size?

### Evidence

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py` — 5,301
  lines; 14 classes (`_OptionGrammar`, `FullQaPattern`, `FullQaMatch`, `_Runner`, `_Launcher`,
  `_Output`, `_PythonHeredoc`, `_Verdict`, `_Operands`, `_Readable`, `_CodeContent`,
  `_ParseMeter`, `_Event`, `SubagentFullQaBlockerHandler` at line 4986); 167 functions and
  methods. The handler class itself starts 94% of the way down the file.
- `NIGGLES.md:1365-1379` — the write-up prescribed the split "after Plan 00463 merges", along
  the seams the file already has, reusing the Plan 00464 script-walk and wrapper machinery
  where recognition duplicates it. `CLAUDE/Plan/README.md:186` — Plan 00463 is Complete.
- Observed during this task, twice: the handler judged `grep -c "^class …" <file>` and
  `grep -c "^\s*$k:" <yaml>` as `unrecognised-interpreter-inline-code` because `-c` sits in a
  generic inline-code flag list (`-e`, `-E`, `-c`, `-r`, `--eval`) that is applied to a program
  the parser does not recognise. `grep -c` counts lines. The verdict was an advisory, not a
  denial, so it cost nothing here — but it is a recogniser defect that a reviewer of a 5,300-line
  file did not see, which is the ledger's own argument.
- `git log` on the file: the last four commits are 00463 rounds and a v3.67.0 review fix; four
  `worktree-*` branches are open on `main` and some gate-fix agents are active in this session.

### Ruling: FIX, as a sequenced pure-refactor plan — not now, and not in the ledger

### Reasoning

Outside the threat model entirely. The size is a review-cost and defect-hiding problem, and the
`grep -c` misclassification above is a live instance of the hiding: a flag table meant for
interpreters is reaching an ordinary search command, inside a module too large for the review
rounds that produced it to have noticed. Accepting the size means accepting more of that.

But a 5,300-line security parser is not refactored while branches that touch it are open: the
split is a rename of nearly everything, so any concurrent gate-fix branch becomes a merge of
every line. The right form is a plan (`mkplan.bash`), with these constraints: pure refactor,
`tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker*.py` and the acceptance tests
unchanged and green before and after; recognisers (`_Runner`, `_Launcher`, `_Output`,
`_PythonHeredoc`, `_OptionGrammar`) move to a `utils/full_qa_recognition/` package beside
`shell_segmentation`, with any piece that duplicates the 00464 script walk or wrapper peeling
replaced by the shared one rather than moved; behaviour-free tables (`_SYNTAX`-style flag
grammars, interpreter lists) move to `constants`; `_Verdict`, `_Operands`, `_Event` and the
messages stay in the handler. It starts only once no open branch has a diff on the file.

Two small items go to the ledger now, not to the plan: the `grep -c` inline-code
misclassification (fix: the inline-code flag heuristic applies only to programs the parser
knows take code on a flag, or `grep`/`awk`-family search commands are excluded from it), and a
one-line module-size check in QA so the next handler cannot grow past a stated bound unnoticed.
