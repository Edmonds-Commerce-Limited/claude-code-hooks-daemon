# Defect ledger — every known defect in the plan tree and holding area

Read-only enumeration, 2026-09-08. Scope read: all 25 active `CLAUDE/Plan/*/PLAN.md`
plus today's JOURNAL day-files, `CLAUDE/UPGRADES/UNRELEASED/`, the three
`260908-assess-{a,b,c}-opus-5.md` reports, `BUG_REPORTING.md`, and the untracked
field reports at the repo root.

**Every claim below was re-verified against the tree**, not taken from the
assessment reports. Where a plan's stated finding turned out to be already fixed,
it is in the "already fixed" section instead, so nobody re-opens it.

Two scope notes. First, `CLAUDE/Plan/00362-client-upgrade-report-fix-all-known-defects/`
was scaffolded during this read and is still an empty template; it is excluded.
Second, the literal instruction named `untracked/*bug*.md`, which is one file. Three
other untracked field reports carry live, reproduced defects
(`upgrade-3.62.0-defects.md`, `hooks-daemon-issues.md`, `hooks-daemon-pipe-white.md`),
so they are included and marked as beyond the literal file list. Excluding them
would have left seven real defects off a ledger whose purpose is that a release
carries none.

Legend for the last column: **W** = self-contained enough for one agent in a
worktree; **W?** = self-contained code change but gated on a decision first;
**N** = not self-contained.

---

## HIGH — fail-open, data loss, or crash

### D1 · Plan 00252 Phase 3 (Tasks 3.1–3.4) · staged content is never inspected for secret-list terms

No guard reads staged blobs, so a file that arrives by `mv` and is then committed
carries a secret-list term into a pushed commit. Verified:
`handlers/pre_tool_use/sensitive_content.py` contains zero occurrences of
`diff --cached` or any staged-content path. The handler checks git *metadata*
only. This already happened once, and a term in a pushed commit needs a history
rewrite.
**Status**: Not Started, all four tasks unticked. · **W**

### D2 · Plan 00172 Finding 1 (Tasks 1.1, 2.1, 2.3, 2.4) · config for 20 of 31 wired events is silently dropped

`daemon/cli.py:2718` builds the handler-config mapping by iterating
`HandlersConfig.model_fields`, and that model declares 11 event fields against 31
wired events. Config for the rest is discarded with no error. The function's own
docstring at `daemon/cli.py:2702` names this plan as the fix. Same failure mode as
the shipped `status_line` config-drop bug, re-armed for every newly-wired event
that gains handlers.
**Status**: Not Started. · **W**

### D3 · Plan 00291 Task 1.1 · the documented fresh-clone upgrade aborts into rollback

`scripts/upgrade_version.sh:566` calls `stop_daemon_safe "$VENV_PYTHON"`. Line 99
lets that variable fall back to empty on a fresh clone (deliberately, per Plan
00104), and `scripts/install/daemon_control.sh:60-63` returns 1 on an empty value.
The script runs under `set -euo pipefail` (line 24), so the documented route
hard-fails and rolls back. Reproduced by a client canary install.
**Status**: Not Started. · **W**

### D4 · Plan 00100 Phase 4 (Tasks 4.0–4.4) · no concurrency protection around venv mutation

Two daemons starting simultaneously both `rm -rf` and `uv sync` the same venv
directory. Verified: zero `flock` occurrences in `scripts/lib/resolve_venv.sh` and
`scripts/install/venv.sh`. Task 4.0 first needs a bind-mount spike, because
`flock` behaviour under the Podman mount is unverified.
**Status**: Dormant, Phase 4 entirely unticked. · **W?** (spike gates the design)

### D5 · Field report `hooks-daemon-issues.md` §1 · `/hooks-daemon health` is unusable on every install

`skills/hooks-daemon/scripts/health-check.sh:67-73` downloads
`bootstrap-checksums.txt` from the GitHub "latest" release before doing anything
and `exit 1`s when the fetch fails. The asset is not attached to the latest
release, so the client saw a 404 and the health check never ran. There is no
fallback to the already-installed local wrapper.
**Status**: not tracked by any plan. · **W** (the local fallback; attaching the
release asset is a separate release-pipeline change)

### D6 · Field report `hooks-daemon-issues.md` §2 · stale handler keys pass validation and the handlers silently do not run

A client config still carried `stop.hedging_language_detector` and
`stop.dismissive_language_detector` after those moved under
`pseudo_events.nitpick.handlers`. The upgrade printed `no config changes`,
`config-validate` reported `valid: true` with no warnings, and both detectors were
simply not running. Thirteen further config keys got the same silence. Protection
disappears with no signal at upgrade or at session start.
**Status**: not tracked by any plan. · **W**

### D7 · Plan 00264 Open Question 7 · a `gh` comment body is inspected for nothing at all

`sensitive_content` reaches git metadata surfaces through a
`_GIT_METADATA_WRITE_SUBCOMMANDS` allowlist, so a `gh issue comment` body is not a
candidate. A secret-list term can therefore reach a public GitHub comment
unexamined, which is more public than most commits. The plan records this as an
unresolved question and explicitly says not to leave it unrecorded; it is
currently owned by neither 00264 nor 00252.
**Status**: Not Started; Question 7 undecided. · **W?** (decide the owner first)

---

## MEDIUM — wrong behaviour

### D8 · Plan 00189 Tasks 1.1–1.3 · daemon-down `WorktreeCreate` writes JSON to a stdout Claude Code reads as a path

The deployed `.claude/hooks/worktree-create:21-24` ends its `ensure_daemon` failure
branch with `emit_hook_error "WorktreeCreate" ... ; exit 0`. Claude Code parses this
hook's stdout as the created worktree's absolute path, so a daemon that cannot
start yields the literal path `/<cwd>/{...json...}`. The `raw_stdout` event flag
now exists (`constants/events.py:146`, set `True` at `:299` and `:470`), so Task
1.3's generalisation substrate has arrived since filing.
**Status**: Not Started. · **W**

### D9 · Plan 00172 Finding 2 (Tasks 1.2, 2.2) · a plugin targeting a worktree event is rejected at validation

The `PluginConfig.event_type` Literal at `config/models.py:328` omits
`worktree_create` and `worktree_remove`, both of which now have built-in handlers.
This fails loud rather than silently, but it is a real feature restriction today,
not the latent one the plan described.
**Status**: Not Started. · **W**

### D10 · Plan 00252 Phases 1–2 · tests take their git identity premise from ambient config

Verified: `tests/conftest.py` has no `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM` or
`GIT_AUTHOR_*` neutralisation. Seven occurrences across Plans 00245 and 00248 went
red on a fresh runner and green locally; six were fixed by hand with no guard for
the class, and the seventh was written in the commit that closed that plan.
**Status**: Not Started. · **W**

### D11 · Plan 00291 Task 2.1 · `truth_changes` rejects the `v`-prefixed tag every doc produces

`install/truth_changes.py:114` `_parse_version` splits on the separator and casts
to `int`, so `v3.62.0` raises. Note the sibling parser in
`install/breaking_changes_detector.py:27` was already fixed to strip the prefix, so
this is the remaining half, not the whole finding.
**Status**: Not Started. · **W**

### D12 · Plan 00291 Task 2.2 · an old-format config is retained silently on install

`install_version.sh` keeps a many-versions-old config without surfacing the
migration advisory, which already exists and works. Recorded from the canary run;
this one is the plan's claim and I did not independently reproduce it.
**Status**: Not Started. · **W**

### D13 · Plan 00329 · the reconciliation report replays superseded truths

`install/truth_changes.py:211` `format_truth_changes_for_llm` emits every entry of
every manifest with no dedup, collapsing or supersession logic. The plan-creation
truth appears three times across v3.23.0, v3.25.0 and v3.26.0, and only the last is
current, so an agent following the instruction literally asserts a claim into the
project's docs and then contradicts it twice. The size half of this plan (89 KB,
74 entries, no bound) is ergonomics rather than a defect; the supersession replay
is the defect.
**Status**: Not Started. · **W?** (Task 1.1 must choose the collapsing key first)

### D14 · Plan 00175 Tasks 1.2, 1.3 · the daemon recommends the refresh interval its own plan concluded is wrong

`handlers/session_start/suggest_statusline.py:26` still sets
`_RECOMMENDED_REFRESH_INTERVAL_S = 10` and renders it into the suggestion body at
`:165` and `:173`, which a fresh project copies. `scripts/install_version.sh`'s
fallback generator writes no `refreshInterval` at all (verified: zero occurrences
in that file). Plan 00175 established `1` as correct and shipped it in
`.claude/settings.json`, so the origins now disagree with each other.
**Status**: Dormant, part-shipped. · **W** (Phase 2's new handler is a separate,
larger judgement call and should not be bundled)

### D15 · Plan 00242 · a terminal ALLOW still ends the chain and disables its successors

`core/chain.py:251` still branches on `handler.terminal`, and Plan 00241's narrow
warn-mode guard remains the only protection over what the plan argues is a
structural problem. No new instance has surfaced since filing, and the plan itself
specifies a config-flagged staged rollout because the change is risky.
**Status**: Not Started, journal holds one "plan scaffolded" entry. · **N**
(4 phases, measurement-gated, behaviour change across every project)

### D16 · Field report `hooks-daemon-issues.md` §4 · `project_containment` denies the harness's own scratchpad

Claude Code's system prompt instructs the agent to use a per-session scratchpad
under `/tmp/claude-*/…/scratchpad` for all temp files; the handler denies every
write there with `R-WRITE-OUTSIDE-PROJECT-ROOT`. The two instructions contradict
each other every session and the agent burns a blocked call learning which wins.
**Status**: not tracked by any plan. · **W?** (whitelist the harness path, or
document the override — an owner call on which)

### D17 · Field report `hooks-daemon-issues.md` §6 · `tdd_enforcement`'s documented escape hatch cannot express a nested mirror layout

`handlers/pre_tool_use/tdd_enforcement.py:528` `_map_src_to_tests_mirror` hardcodes
`tests/<mirror>` and `:563` `_map_src_to_test_path` hardcodes `tests/unit/`, while
`test_path_map` is documented as FLAT. For a `tests/Small/<mirror>` layout none of
the five searched locations can ever match, so the gate would block every new
source file and the client disabled it. The declared remedy does not work for the
layout it was meant to serve.
**Status**: not tracked by any plan. · **W**

### D18 · Plan 00330 Task 1.4 · docs QA and plan QA ignore `daemon.exclude_paths`

Verified: zero references to `exclude_paths` in either the `docs_qa` or `plan_qa`
package, against 12 handler modules that honour it via `utils/path_exclusion.py`.
The shipped guidance repeatedly offers `daemon.exclude_paths` as the project-wide
way to exempt paths, so a user configuring ignored directories through it gets
silence from docs QA — the same symptom as the `scope_exclude_globs` bug fixed in
`0054105b`. The plan deliberately did not fix it on sight, because honouring it
would silently stop deliberately-bad fixture trees producing findings.
**Status**: Not Started. · **W?** (owner decision on intent gates the change)

---

## LOW — cosmetic or diagnostic

### D19 · Plan 00159 Task 2.1 · Pyright reports `int | None` at seven deref sites in `supervise()`

`.claude/ccy/claude-supervise.py` resolves `stdin_fd` to a non-None value, but the
`_on_winch` closure captures it and Pyright discards the narrowing. Runtime-safe
and outside the mypy QA gate, so it never blocked. Fix is a fresh non-optional
local. Line numbers in the plan are approximate and have drifted; locate by symbol.
**Status**: Not Started. · **W**

### D20 · Field report `hooks-daemon-issues.md` §8 · `optimise` Step 0 silently skips in every consumer install

`skills/hooks-daemon/scripts/optimise-invoke.sh:69` lists manifests under
`CLAUDE/UPGRADES/config-changes/v*.yaml`, a tree that exists only in the daemon's
own repo. Line 82 tells the agent to skip the step when the directory is absent, so
the skip is now documented — but the consequence stands: the "new since vX"
recommendations never surface for a consumer.
**Status**: not tracked. · **W**

### D21 · Field report `hooks-daemon-pipe-white.md` diagnostics · `debug_info.py` fails inside its own report

Two `[Errno 13] Permission denied: ''` failures in the script's own "Daemon Status"
and "Installed Handlers" sections, consistent with an empty command string being
executed. Every bug report generated by the documented tool carries them.
**Status**: not tracked; reporter flagged it as a separate minor bug. · **W**

### D22 · Field report `hooks-daemon-issues.md` §3 · `echd-capture` was named but absent

`pipe_blocker` guidance names `echd-capture` as the preferred path and the client's
container had no such binary. Since then `scripts/echd-capture` exists and
`scripts/install/hooks_deploy.sh` deploys it, and the guidance now says the block
message prints an absolute path. **Re-verify against a client install before
spending effort** — this may already be closed.
**Status**: probably fixed. · **W**

---

## Defect risk — real, but not yet a confirmed defect

**R1 · Plan 00327 · the vendored hook contract has not been audited against current upstream.**
`contracts/claude-code-hooks/META.json:5-6` records `docs_sha256` `d514bf57…` and
`last_audited_claude_code_version` `2.1.252`; the installed Claude Code is 2.1.263
and the upstream document now hashes differently. The daemon enforces itself
against 33 hand-derived schemas, so any claim that drifted is enforced as if it
were documented. Nothing is known to be wrong — the point is that nobody knows.
A release asserting "no known defects" cannot rest on an unaudited contract, so
Phase 1's delta measurement belongs in this push even though no defect is proven.
**N** — the extraction is a verified human/agent step by design.

**R2 · Plan 00159 Phase 1 · nine writers share a pid-keyed temp filename.**
`goal_injection.py:432` and `:477`, `compaction_signal.py:81`,
`context_sidecar.py:195`, `standing_authorisations.py:272`, `thread_registry.py:113`,
`model_fallback_detector.py:467`, `downgrade_state.py:215` and
`utils/model_downgrade_signal.py:212` all use `.{stem}.{os.getpid()}.tmp`. The
plan's own Overview calls this "robustness hardening, not a live bug", and it is
right: one status-line subprocess per session makes same-session concurrency
unreachable today. It is listed because the count grew from the four the plan
enumerated to nine unprompted — the pattern spreads by copy. **W**, cheap.

---

## Plans whose remaining work is entirely non-defect — exclude from this push

| Plan  | Remaining work                                                | Why not a defect                                                                   |
| ----- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 00085 | 8 phases of adaptive-trigger + workflow-reminder feature work | The first consumer's data source no longer exists; cancel candidate                |
| 00129 | Adopt an external repo as a major dependency                  | A want with no defect behind it; audit verdict was NOT READY                       |
| 00135 | Nothing — ARCH-A phases are the shelved fallback              | Delivered and running; today's journal records the evidence                        |
| 00144 | Task 4.4 only                                                 | One human go/no-go on a `warn`→`block` ratchet, zero code                          |
| 00158 | Phases 2–4, `subagentStatusLine` rendering                    | New feature; its blocker needs a fresh design decision, not a fix                  |
| 00163 | Task 3.2 only                                                 | One human ratchet decision, zero code                                              |
| 00170 | Tasks 4.1–4.3, 5.1–5.2                                        | 4.1 moot at 31/31 wired, 4.2 delivered by Plan 00271, 4.3 is convenience           |
| 00204 | Phases 1–3                                                    | The gap is live but the guidance disclaims it at `security_antipattern.py:131,275` |
| 00266 | Phases 2–5                                                    | Dormant by design; written revival conditions are all unmet                        |
| 00280 | All phases                                                    | Advisory-text feature; ships dormant here (`enabled: false`); cancel candidate     |
| 00344 | Phases 1–3                                                    | Blocked on telemetry spread the data does not yet have                             |
| 00361 | Task 3.1 only                                                 | The fix shipped at `da5b7258`; what remains is a live check after a ccy restart    |
| 00160 | Task 2.4                                                      | Phase 2 code shipped; Phase 3 subsumed by Plan 00166. Verification debt, not a bug |

Partial exclusions on plans that also carry defects above: 00100 Phases 3.5, 5 and
6 (wiring an orphaned helper, test infrastructure, docs); 00264's size-cap half
(a new feature responding to a field incident); 00291 Phase 3 (the guarded
branch-install mechanism, an owner-ruled feature); 00329's bounding half; 00330
Phases 1–4 except Task 1.4.

---

## Already fixed — do not re-open

Each of these is recorded as a defect somewhere in scope and is closed in the tree.
Listing them so the push does not spend effort on them.

From `untracked/upgrade-3.62.0-defects.md`, all six:

1. `config-merge` dropping top-level sections — fixed, `install/config_merger.py:146`
   calls `_apply_custom_sections`, which deep-merges the user's sections.
2. Config preservation crashing on a backslash — fixed,
   `scripts/install/config_preserve.sh:395-402` now feeds the JSON on stdin
   (`<<< "$merge_output"`) instead of interpolating it into a source literal.
3. `parse_version` rejecting a `v` prefix — fixed in
   `install/breaking_changes_detector.py:27`, which strips it and documents why.
   (The `truth_changes.py` sibling is still open — that is D11.)
4. A step added in a release not running during the upgrade to it — fixed,
   `scripts/upgrade_version.sh:1295` re-execs the target version's script.
5. `BUG_REPORTING.md` pointing at `/tmp` — fixed, it now says `untracked/scratch/`
   and explains why.
6. The "MANDATORY NEXT STEP" false claim — fixed, `upgrade_version.sh:1259-1262`
   now says new handlers are registered and firing with default settings.

Also closed:

- `pipe_blocker`'s `extra_whitelist` crashing the handler on every piped command
  (fail-open, whole handler skipped) — fixed; `pipe_blocker.py:391` now holds
  `list[str]` and matching goes through `_matches_any_configured` at `:731`.
- `secret_file_guard` reading a bracket expression as a wildcard — Plan 00356,
  archived, release note 03 pending.
- A malformed glob raising and skipping the quarantine guard — Plan 00357,
  archived, release note 02 pending.
- The supervisor's coupled `/effort` lagging a forced `/model` switch, from
  `fedora-desktop-ccy-CLAUDE-bug.md` — fixed; `claude-supervise.py:4741-4748` now
  gates on an empty input box only and cites this exact allowance-burning failure.
- Skill/CLI verb mismatch `validate-config` vs `config-validate` — no occurrence of
  the wrong verb remains anywhere under `skills/`.

Two items in `fedora-desktop-ccy-CLAUDE-bug.md` are defects in **ccy itself**, not
in this repository: the startup security gate's allowlist disagreeing with ccy's
own `.claude/ccy/.gitignore` whitelist, and its prescribing `git filter-repo` plus
a force push as the only remedy. They need filing upstream with the ccy
maintainers; nothing in this repo can fix them. The report's follow-up worry that
the promoted contract doc became homeless is resolved: `.claude/ccy/CLAUDE.md`
exists on disk (deliberately untracked, so the gate stays quiet) and
`.claude/rules/ccy-supervisor-dogfooding.md` is present and points at it.

---

## Suggested order

D3, D5 and D6 first: each breaks a documented route for every client, each is small,
and all three are invisible until someone upgrades. Then D1 and D7 together — they
are the same missing guard on two surfaces, and both fail toward a disclosure that
cannot be undone. D2 and D9 are one file and should ship as one change. D15 and R1
are the only two items that genuinely cannot be handed to a single worktree agent.
