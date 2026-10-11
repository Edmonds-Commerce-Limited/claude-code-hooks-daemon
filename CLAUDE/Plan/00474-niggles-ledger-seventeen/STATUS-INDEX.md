# Plan 00474: status index

One line per niggle with its verdict, origin and status; [NIGGLES.md](NIGGLES.md) holds the full write-ups and [PLAN.md](PLAN.md) the task state.

| #          | Verdict                                                                                                                      | Origin              | Status                                |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------- |
| N424       | LSP symbol-lookup guard denies a grep over a CLI's piped stdin, where no language server could answer                        | Coordinator         | ⬜ Open                               |
| N423       | Unrequested `/goal clear`: the designed retraction (all goal plans Blocked); a latent plan-root bug fixed alongside          | Owner report        | ✅ Closed: by design; latent fix (AO) |
| N422       | Main is red: two `tests/unit/config` invariants fail (handler options read by hand; `AGENT_ID_EVENTS` short of 3 events)     | Coordinator         | ✅ Fixed (batch AO)                   |
| N421       | The upgrade-approval guard denies a plain pytest run with `PYTHONPATH` and a `$(...)` interpreter (B5)                       | Coordinator         | ✅ Fixed (batch AO)                   |
| N420       | ARCHITECTURE.md says the hook layer fails open when the daemon does not answer; the README says it does not in general       | Fact-check          | ✅ Fixed (ARCHITECTURE.md)            |
| N419       | `subagent_full_qa_blocker` judges an unknown program by flag shape alone (`ps -e`, `docker run -e`); GitHub Issue #69        | Issue #69 triage    | ✅ Fixed (batch AL)                   |
| N418       | A helper that calls its own parameter ranks every call through it as may-run, whatever the call site passes                  | Batch AG review     | ✅ Fixed (batch AH); 🚫 limits        |
| N417       | `subagent_full_qa_blocker` reads `pytest` text inside Python string data as a command (unmasked by N416's fix)               | Batch AE review     | ✅ Fixed (batch AG); residuals        |
| N416       | `subagent_full_qa_blocker` advisory on `set -e`, `uniq -c` and other non-interpreter `-c`/`-e`/`-r` commands                 | Batch AB review     | ✅ Fixed (batch AE)                   |
| N415       | `subagent_full_qa_blocker` misses `fh = open(p); src = fh.read(); exec(src)`                                                 | Batch AB review     | ✅ Fixed (batch AE, AK); 🚫 limits    |
| N414       | Staging simulation residuals: `--refresh` without `-q`, `git diff --output=`, the blunt `<` test                             | Batch AC review     | ✅ Fixed (batch AE)                   |
| N413       | `PipBreakSystemHandler` quadratic on a long nested-substitution word                                                         | Batch AB            | ✅ Fixed (batch AD)                   |
| N412       | The daemon reads neither `mcp_server.source` nor the `mcp__<server>__` tool-name prefix                                      | Write-up            | ✅ Closed, no consumer                |
| N411       | The Stop hook's 8-continuation cap may defeat the Stop handlers; one open question                                           | Write-up            | ✅ Fixed (batch AL)                   |
| N410       | `upgrade_approval_guard` denies a QA tool reached through a variable once `PYTHONPATH` is set                                | Write-up            | ✅ Fixed (batch O)                    |
| N409       | `subagent_full_qa_blocker` denies an ordinary `python3 script.py` as a whole-suite run                                       | Write-up            | ✅ Fixed (residuals in body)          |
| N408–N407  | `gh_*_comments`, `pip_break_system`, `sudo_pip` deny text that only mentions the flag (N407 skips obfuscation)               | Write-up            | ✅ Fixed (batch H)                    |
| N406–N404  | `github_auto_close_keywords`, `ancestry_preserving_merge`, `git_message_backtick` deny quoted mentions                       | Write-up            | ✅ Fixed (25b9ae109)                  |
| N403       | `project_containment` ignores a preceding `cd`; a never-run loop and `eval "$name"` are documented limits                    | Write-up            | ✅ Fixed (8db7b9d78); 🚫 limits       |
| N402       | The conflict-marker gate denies `cd "$(git rev-parse --show-toplevel)" && git commit`; part (b) is a ruling                  | Write-up            | ✅ Fixed (batch AL)                   |
| N401–N400  | `destructive_git` and `git_stash` read a quoted heredoc body as a command                                                    | Write-up            | ✅ Fixed (f189ea120)                  |
| N399–N398  | `sed_blocker` denies a message that mentions sed; two worktree acceptance probes fail                                        | Write-up            | ✅ Fixed                              |
| N397       | Copy-flag parsing and the `find -exec` list are re-implemented per handler; the copy half is not separable                   | Write-up            | ✅ Ruled B: left as is                |
| N396       | The ccy supervisor's copy of the self-install rule still uses `.exists()` (live supervisor)                                  | Write-up            | 🔄 Ruled A (supervisor)               |
| N395–N390  | `canonical_callers`, advisor text, verdict-log rule IDs, xdist lock gate, install-mode and git option readers                | Write-up            | ✅ Fixed                              |
| N389       | The development host's real name is in tracked plan files                                                                    | Write-up            | 🔄 Ruled A, B; #108                   |
| N388–N386  | Host-segment role override, inline-suppression detector on ignored code, self-install rule copies                            | Write-up            | ✅ Fixed                              |
| N385       | Careless spellings the raw-text guards allow on main; the shapes left open are decided limits                                | Write-up            | ✅ Fixed; 🚫 limits recorded          |
| N384–N379  | `optimise` relevance, quoted git option values, `changed --range`, pytest drift, branch and merge gates                      | Write-up            | ✅ Fixed                              |
| N378       | The `[awaiting-human]` marker is one project-wide file; owner ruled "fine to leave" (Plan 00501 may replace it)              | Write-up            | 🚫 Deliberate limit                   |
| N377       | Synthetic sessions still read the account's live usage in three more places                                                  | Write-up            | ✅ Fixed                              |
| N376       | Four tests fail under the full gate's concurrent load; the sweep half needs a serial-phase design                            | Write-up            | 🟡 Part fixed; ruled: #107            |
| N375       | The hook contract audit is at Claude Code 2.1.272 and the upstream hooks doc has changed                                     | Write-up            | ✅ Fixed (batch N report)             |
| N374       | v3.69.0 release code review; defects fixed, one cold-index glob advisory residual is a decided limit                         | Write-up            | ✅ Fixed; 🚫 residual                 |
| N373       | An invalid `stand_in_delay_hours` unregisters the Stop handler; `bash_safe_mode` gained the same `validate_options` (N374)   | Write-up            | ✅ Fixed                              |
| N372–N370  | Daemon-docs guard on the repo folder name, per-clone plan counter, sed guard on a `git -C` message                           | Write-up            | ✅ Fixed                              |
| N369       | A forwarder integration test fails inside every harness worktree and passes on main                                          | Write-up            | ✅ Fixed (batch AC)                   |
| N368–N362  | Fact-checker evidence, QA venv recipe, `git config` read, fenced token, `bash -c` pipe, merged-branch delete                 | Write-up            | ✅ Fixed                              |
| N361       | The fake-values registry is not pre-filled; a commit-time BLOCK for a bad entry names no severity                            | Write-up            | ✅ Fixed (batch M, AM)                |
| N360–N355  | Opt-in handlers across an upgrade, fact-check feed and records, protected-file index, nested-eval cost                       | Write-up            | ✅ Fixed                              |
| N354       | The upgrade guard denies a `PYTHONPATH=… python -c` probe; a name built at run time is unseen (threat model)                 | Write-up            | ✅ Fixed; 🚫 limit                    |
| N353–N343  | Dismissive-language, scan deadline, lock file, glob caps, scaling harness, timeouts, journal conflicts, CHANGELOG            | Write-up            | ✅ Fixed                              |
| N342       | `setup_worktree.sh` cannot create any worktree from a host checkout whose path leaves no socket room                         | P487 host agent     | 🔄 Ruled: git min version; #110       |
| N341–N338  | Four guard false positives met by the Plan 00487 host agent ([table](NIGGLES.md))                                            | P487 host agent     | ✅ Fixed                              |
| N337       | Gate the supervisor's idle `/compact` on `prompt_cache.warm` (live supervisor)                                               | Plan 00486          | 🔄 Ruled inverse; #109                |
| N336       | Make the supervisor's red-zone `/compact` aware of the `/autocompact` window (live supervisor)                               | Plan 00486          | 🔄 Ruled: reject bad config           |
| N335–N331  | `/doctor prompt-audit` compared; `.claude/rules` loading is no defect; `run_in_background` text                              | Plan 00486          | ✅ Fixed or closed                    |
| N334       | Re-check the supervisor's post-compaction `/goal` and `continue` re-injection (live supervisor)                              | Plan 00486          | 🔄 Ruled check, remove; #106          |
| N333       | How `usage_pause` should interact with Claude Code's "continue automatically at usage limit"                                 | Plan 00486          | ✅ Ruled A: left alone                |
| N330       | Read `rate_limits.spend_limit` in `core/usage_snapshot.py`; adopt when a consumer is wanted                                  | Plan 00486          | ✅ Fixed (batch AM)                   |
| N329–N312  | Changelog-review and gate follow-ups: errexit, gated-install record, relay build, journal QA, module length                  | Write-up            | ✅ Fixed                              |
| N311       | `upgrade_approval_guard` denies `(PYTHONPATH=… python -m pytest …)` in a subshell                                            | Safe-mode agent     | ✅ Fixed (22429c3a5)                  |
| N310       | `changed` selects no tests for "too-broad" files, so template/priority invariants broke main unseen                          | Coordinator         | 🔄 Instances fixed (2be30049c)        |
| N309       | `remote-docs add` refuses a docs page whose example carries a session-UUID-shaped id                                         | P479 agent          | ✅ Fixed (Plan 00492)                 |
| N308       | Owner ruling: block unguarded `;` chaining (`bash_safe_mode` to block mode in this repository)                               | Owner               | ↩️ Reversed by ruling A3              |
| N307       | In a command with two `git commit`s, the second commit's pathspecs are never scanned                                         | N299 review         | ✅ Fixed (530ffc83d)                  |
| N306       | The commit-move reader records both directories of `cd a \|\| cd b`                                                          | N299 review         | ✅ Fixed (530ffc83d)                  |
| N305       | `staged_lint_gate` judges a `cd other-repo && git commit` as this repository's commit                                        | N299 agent          | ✅ Fixed (n304-n305-gate-dirs)        |
| N304       | `guard_config_commit_gate` misses `cd .claude && git commit hooks-daemon.yaml`                                               | N299 agent          | ✅ Fixed (n304-n305-gate-dirs)        |
| N303       | The pause-gate merge left a PreToolUse handler unclassified; main was red (N278/N297 again)                                  | N299 agent          | ✅ Fixed (1c4f8e25f)                  |
| N302       | `subagent_full_qa_blocker` reads `grep -c` / `awk -e` as interpreter inline code (advisory noise)                            | P483 triage, Fable  | ✅ Fixed (1078e4291)                  |
| N301       | Each commit gate checks every pathspec with two git calls per path, separately                                               | N245 review         | ✅ Fixed (37b9a8020)                  |
| N300       | `remote_docs_commit_gate` judges a nested worktree's commit against this repository                                          | N245 review         | ✅ Fixed (37b9a8020)                  |
| N299       | After `cd sub`, `sensitive_content` resolves `git commit -m x f.txt` from the repo root                                      | N245 review         | ✅ Fixed (37b9a8020)                  |
| N298       | `R-PLAN-NUMBER-DISCOVERY` denies a read-only `ls CLAUDE/Plan/*/PLAN.md`, even as quoted text                                 | P483 triage         | ✅ Fixed (quoted-text-fps)            |
| N297       | The coordinator merged `merge_qa_advisor` without a targeted run; main failed two tests (N278 again)                         | Coordinator         | ✅ Fixed (3dadb3d8c)                  |
| N296       | `audit_error_hiding.py` sees log-and-continue only as a direct `logger.<level>()`; a helper call evades it                   | N294 review         | ✅ Fixed (e90cbd63c)                  |
| N295       | The prompt-cache chip parses every sub-agent sidecar (3,369 files) on every render: 84–427 ms                                | Coordinator         | ✅ Fixed (b44e395a5)                  |
| N294       | A status-line client that hangs up still logs an ERROR: `writer.wait_closed()` raises in `finally`                           | Coordinator         | ✅ Fixed (fc6782bf1)                  |
| N293       | #68: secret/quarantine guards fail closed on an absolute glob with 2+ wildcards under an existing literal prefix             | GitHub #68          | ✅ Fixed (92b9b49e0)                  |
| N292       | `upgrade_approval_guard` denies `PYTHONPATH=… $V/python script.py`, which runs no upgrade                                    | Coordinator         | ✅ Fixed (15fe504c1)                  |
| N291       | `secret_file_guard` denies a grep regex inside `$( )` as a mention of a protected path                                       | Coordinator         | ✅ Fixed (4a30b9248)                  |
| N290       | The coordinator stated a confident, unsearched, false claim ("the supervisor is outside this repository")                    | Owner               | 🔄 Plan 00480                         |
| N289       | In this repository the slow SessionStart sweeps appear never to reach a session, unreported                                  | Coordinator         | ✅ Fixed (76cf82266)                  |
| N288       | An event-socket test fails wherever the pytest process exports a hostname override                                           | Task 4.1 agent      | ✅ Fixed (test only)                  |
| N287       | `semgrep` and `dependencies` fail on main; neither runs in CI or in `changed`                                                | Plan 00475 timing   | ✅ Fixed (9342fa898)                  |
| N286       | Main full CI went red after N264/N266: a playbook probe, a blindness verdict and a skip-list finding                         | Main CI             | ✅ Fixed (1bbf676a0)                  |
| N285       | `PYTHONPATH=` before an interpreter held in a variable is denied as an upgrade-approval bypass                               | N283 agent          | ✅ Fixed (a9d6d9aa0)                  |
| N284       | The pipe blocker reads `\|` inside a double-quoted grep pattern as a pipe                                                    | Coordinator         | ✅ Fixed (72e9018e3)                  |
| N283       | `secret_file_guard` misses a protected name in git `rev:path` syntax at the repository root (security)                       | N253 analysis       | ✅ Fixed (caa8ff966)                  |
| N282       | The N264 cross-worktree guard judges an in-process teammate by the coordinator's working directory                           | Coordinator         | ✅ Fixed (8eeead3e5)                  |
| N281       | A hostile-input sweep failed on slow runners: the 100,000-character scan timed out and denied (fail-closed)                  | Main CI             | ✅ Fixed (test only)                  |
| N280       | Something with pre-N271 code wrote an older `CLAUDE.md` guidance section into main during a test run                         | Coordinator         | ✅ Guarded (AN); 🔄 follow-ups        |
| N279       | `changed_tests` once selected 50 test files, ran 0 tests and still passed                                                    | p477 agent          | 🟡 Detection fixed, cause not found   |
| N278       | A branch merged with its targeted QA never run; main took three static-check failures                                        | Coordinator         | 🔄 Plan 00475 Task 4.2                |
| N277       | `_resolve_python_cmd` in `init.sh` returns 0 after a failed resolve, with `PYTHON_CMD` empty                                 | p477 agent          | ✅ Fixed (f794ae2d6)                  |
| N276       | The SessionStart chain overruns its 20 s budget under load, so declared crons are never asked for                            | Coordinator         | ✅ Fixed (aa557cc12)                  |
| N275       | `secret_file_guard` judges an Edit of a YAML workflow holding `${{ }}` as an unreadable shell command                        | Coordinator         | ✅ Fixed (d66d0ff9b)                  |
| N274       | `AskUserQuestion` is denied as "unattended" right after the owner typed a message                                            | Coordinator         | ✅ Fixed (93cc3615d)                  |
| N273       | A stalled CI job holds main's queue for up to six hours; no job sets `timeout-minutes`                                       | Main CI             | ✅ Fixed                              |
| N272       | One `llm_qa changed` run reported `project_handlers` as 0 tests collected; it passed 232 alone                               | Coordinator         | ✅ Fixed                              |
| N271       | An upgrade fails "uv not found" when the only uv is outside the trusted PATH and `~/.local/bin`                              | Main CI red         | ✅ Fixed (85bea8da6)                  |
| N270       | The workspace venv has drifted from `uv.lock` (pytest 9.1.1 against 9.0.3)                                                   | Coordinator         | ✅ Fixed (re-synced)                  |
| N269       | `secret_file_guard` expands a single-quoted grep regex as a filename glob                                                    | Coordinator         | ✅ Fixed (a7ebcae9b)                  |
| N268       | A symlinked-project daemon test's teardown refuses a daemon that is exiting                                                  | Main CI             | ✅ Fixed (1a61af7d0)                  |
| N267       | Dropping a stale branch always needs a human, even when nothing can be lost                                                  | Owner               | ✅ Fixed (74dbdc970)                  |
| N53        | Ledger 00466: WorktreeCreate exit 127 under the daemon; 127 mechanism reproduced (batch AJ); live cause awaits a recurrence. | 00466 close-out     | 🟡 Diagnostic extended (batch AJ)     |
| N96        | 00466: `subagent_full_qa_blocker.py` is one 5,300-line handler; split graduated                                              | 00466 close-out     | 🔄 Plan 00485                         |
| N222 work  | Saved `tests/scaling.py` diff obsolete: 4115b5f9e, d97464d6e superseded it ([saved](UNFINISHED-N252-SCALING.md))             | 00466 cleanup       | ✅ Fixed (batch D)                    |
| 22 entries | Carried from the dropped `worktree-n466-small-a` branch ([list](CARRIED-REFIX-BRANCHES.md))                                  | 00466 cleanup       | ✅ 0 open (bodies)                    |
| 15 entries | Carried from the dropped `worktree-p422-close` branch ([list](CARRIED-REFIX-BRANCHES.md))                                    | 00466 cleanup       | ✅ 0 open (bodies)                    |
| 14 entries | Carried from the dropped `worktree-d-00421` branch ([list](CARRIED-REFIX-BRANCHES.md))                                       | 00466 cleanup       | ✅ 0 open (bodies)                    |
| 4 entries  | Carried from the dropped upgrade-scripts, 464 and N38 branches ([list](CARRIED-REFIX-BRANCHES.md))                           | 00466 cleanup       | ✅ 0 open (bodies)                    |
| N266       | `flaggable_content_channel_guard` denies greps that never touch a flagged path                                               | Coordinator         | ✅ Fixed (ba47e2459)                  |
| N265       | `secret_file_guard` spends about 2.2 s of CPU on one realistic Python program                                                | N101 CI red         | ✅ Fixed (e39b1f98f)                  |
| N264       | A sub-agent's edits landed, uncommitted, in another branch's worktree                                                        | 00466 landing       | ✅ Fixed (7ebef17fb)                  |
| N246       | Plan and docs QA judge a same-command `git add` as two partial trees                                                         | Carried, N53 branch | ✅ Fixed (530ffc83d)                  |
| N245       | A pathspec commit is judged on the index as well as the named paths                                                          | Carried, N53 branch | ✅ Fixed (17b0aa491)                  |
| N244       | The QA commit gates judge the disk, not the tree the commit records                                                          | Carried, N53 branch | ✅ Fixed (52fd9cd9b)                  |
| N189       | No commit gate sees a commit hidden in text only bash reads (`bash -c "$X"`)                                                 | Carried, N53 branch | ✅ Dismissed (threat model)           |
| N177       | No commit gate sees a commit after a `case` inside `function f {` in `$( )`                                                  | Carried, N53 branch | ✅ Dismissed (threat model)           |
| N176       | No commit gate sees a commit inside `$(( $(…) ))` arithmetic                                                                 | Carried, N53 branch | ✅ Dismissed (threat model)           |
| N135       | No commit gate sees a commit run from text, via an alias, or after `builtin cd`                                              | Carried, N53 branch | ✅ Dismissed (threat model)           |
| N89        | A data-sink receiver is trusted after the command redefines it (`cat() { bash; }`)                                           | Carried from 00466  | ✅ Dismissed (threat model)           |
| N78        | Exotic shapes in the `gd5_exotic` baseline: a trailing `#c` and backslash-octal in a word                                    | Carried from 00466  | ✅ Dismissed (threat model)           |
| N77        | Four shell shapes run a protected-path read unjudged (`bash -c "$x"`, `eval "$x"`, alias, written script)                    | Carried from 00466  | ✅ Dismissed (threat model)           |
| N72        | A Python script's computed subprocess argv is dropped, not judged unresolved                                                 | Carried from 00466  | ✅ Dismissed (threat model)           |
| N71        | The check-to-run race of the commit-gate script walk is undocumented                                                         | Carried from 00466  | ✅ Dismissed (threat model)           |
| N68        | A moved-away daemon checkout reads NOT_INSTALLED and fails open                                                              | Carried from 00466  | ✅ Dismissed (threat model)           |
| N57        | `secret_file_guard` misses a path reached through an earlier assignment, alias or written file                               | Carried from 00466  | ✅ Dismissed (threat model)           |
| N45        | A NUL byte in `secret_word_list_path` raises an uncaught ValueError                                                          | Carried from 00466  | ✅ Dismissed (threat model)           |
| N74        | A recursive `grep -r` over an ancestor of a protected path is allowed                                                        | Carried from 00466  | ✅ No change (Fable ruling; A2)       |
| N62        | Nothing bounds a subagent's context, so long-lived agents burn the usage budget                                              | Carried from 00466  | ✅ No change (Fable ruling)           |
| N256       | Quoted heredoc bodies are glob-walked; a hit cap reads as an evaluation error                                                | Carried from 00466  | ✅ Part 1; part 2 → Plan 00478        |
| N255       | `git commit -F - <<'EOF'` denied as an evaluation error (ENAMETOOLONG)                                                       | Carried from 00466  | ✅ No repro (efe0ec517)               |
| N254       | Two resolvers disagree on `secret_word_list_path`                                                                            | Carried from 00466  | ✅ Fixed (9b589c4fc)                  |
| N253       | `secret_file_guard` exemptions parse options from open lists                                                                 | Carried from 00466  | ✅ Fixed (dbb744f26)                  |
| N263       | The release empties UNRELEASED post-upgrade tasks but not the README index                                                   | v3.67.0 CI          | ✅ Remedied                           |
| N262       | The release procedure has no check that the notes fit a GitHub release body                                                  | v3.67.0 publish     | ✅ Remedied (ea8dcd542)               |
