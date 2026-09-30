# Plan 00376 — fresh whole-branch adversarial review (260925, Opus 5.5)

Branch `worktree-d-00376` at HEAD `ba312329`, merged with main `af7b3c07`.
Read-only. Diff reviewed: `git diff af7b3c07...HEAD`.

**Counts: 1 blocker, 1 major, 8 minor, 4 nit. Verdict: NOT READY.**

The blocker is a full bypass of the human-approval gate that is this plan's
central goal: an agent using the DOCUMENTED upgrade route with `PATH` steering,
across two ordinary command calls, deploys a MAJOR upgrade with no owner
approval and no acknowledgement. It reopens the previous round's MAJOR 4
through a route the `upgrade_approval_guard` does not recognise. Everything the
prior review closed still holds; this is a coverage gap between the guard and
the gate, not a regression in either alone.

## Probe harness (all payloads carry `synthetic_source`)

- `/workspace/untracked/scratch/probe_376r_e2e.py` — drives the REAL Layer 1
  (`scripts/upgrade.sh`), reusing the review-00376 origin/project builders in
  `probe_376_e2e/probe.py`. Scenarios: `tmproutepath` (the blocker),
  `faketimeout`, `docmarker`, `pth`, `ptyapprove`, `repairstamp`. Logs under
  `probe_376r_runs/<scenario>/`; summaries in `probe_376r_*_out.txt`. A first
  pass with no installed doc is in `probe_376r_e2e_out_run1_unknown_range.txt`.
- `/workspace/untracked/scratch/probe_376r_resolve_venv.py` +
  `probe_376r_resolve_venv_out.txt` — the N37 cache rule (symlinks, trailing/
  doubled slash, `..`, a planted foreign/symlinked entry, a second line,
  latency).
- `/workspace/untracked/scratch/probe_376r_guard.py` +
  `probe_376r_guard_out.txt`, `probe_376r_guard_stamp_out.txt` — the
  handler's `matches()` on 30 synthetic Bash/Write payloads.
- Docs/release-notes were reviewed by a fork; its detail is at
  `/workspace/untracked/agent-reports/auto/260925-020403-fork-ab08f6f4d08e5a661.md`
  and folded in below (D1–D8, N-series).

---

## BLOCKER 1: an agent deploys a MAJOR with no approval, via the documented route + `PATH`

The `upgrade_approval_guard` promises (release note 67, `LLM-UPDATE.md:212`,
`HANDLER_REFERENCE.md:1061`) that setting `PATH` (or `HOOKS_DAEMON_PYTHON`,
`GIT_*`, …) on an upgrade command is denied. It is not denied on the route the
docs themselves tell an agent to use, and the gate resolves its own tools
through `PATH`, so the two gaps compose into a complete bypass.

**Root A — the guard misses the documented invocation.**
`_UPGRADE_ENTRY_RE` (`upgrade_approval_guard.py:156-158`) matches only the
literal script *names* `upgrade.sh` / `upgrade_version.sh` /
`upgrade_gate_standalone.py`. `_bash_sets_bypass_env_var` (`:238-248`) denies a
steering var ONLY when a segment also matches that regex. But
`LLM-UPDATE.md` step 3 and the "after a stop, re-run" comment, `README.md`,
`BUG_REPORTING.md` and `.claude/agents/release-agent.md` all fetch Layer 1 to a
temp file and run it as `bash "$tmp" --project-root …`. `bash "$tmp"` names no
guarded script. Probe (`probe_376r_guard_out.txt`):

```
allow  documented route with HOOKS_DAEMON_PYTHON   (HOOKS_DAEMON_PYTHON=/x bash "$tmp" --project-root P v4.0.0)
allow  documented route with PATH                  (PATH=/x/bin:$PATH bash "$tmp" --project-root P v4.0.0)
allow  documented route, export PATH first
DENY   full documented route with PATH             (only because it also contains `git show …:scripts/upgrade.sh`)
```

So the guard catches the one-liner that fetches-and-runs in a single command,
but not the two-call shape — fetch once, then re-run — which is exactly what
the gate's own stop instructs and what an agent naturally does across turns.

**Root B — the gate resolves `timeout`, `git`, python through `PATH`.**
`run_pre_deploy_phase` runs the gate as `timeout "$GATE_TIMEOUT_SECONDS" "$GATE_PYTHON" -I "$gate_script"` (`upgrade_version.sh:402-403`) with `timeout`
unqualified. The detection scan resolves `git` with `shutil.which`
(`upgrade_tasks.py:291`), and on a stampless clone `_pick_gate_python`
(`upgrade_version.sh:339-349`) falls back to `find_latest_python`, which
searches `PATH`. Any of these can be a plant.

**End-to-end, exploited through the real Layer 1**
(`probe_376r_tmproute_out.txt`, `probe_376r_runs/tmproutepath/`): a project
with v3.66.0 installed; a fake `timeout` on `PATH` that prints
`gate-verdict=proceed` for the gate and `exec`s the real one otherwise; the
target's Layer 1 fetched to a file; then

```
PATH=<fakebin>:$PATH bash "<tmp>/upgrade.sh" --project-root <project> v4.0.0
```

Result: `exit=0`, `head=v4.0.0`, `deployed=True`, `hooks_dir=True`,
`marker exists=False`. `1-major-tmp-route-fakepath.log:32` shows the gate line
printed, then deploy proceeds at `:43` with no reading, no acknowledgement and
no approval marker. The `gate-verdict=proceed` stdout guard
(`upgrade_version.sh:410`) is satisfied because the fake prints exactly that
line.

None of the three commands (`git show …` to a file; write+`chmod +x` a fake
`timeout`; `PATH=… bash "$tmp" …`) is denied by any handler. Splitting the
`git show` from the `bash "$tmp"` defeats the one guard segment that would have
fired.

**Why this is a blocker, not a minor.** The plan's stated goal is "an explicit
proceed/abort gate that works for an AGENT … with escalation to the owner when
the change warrants it," and Success Criterion "the proceed/abort gate fires
for a non-interactive agent." Here a non-interactive agent deploys a MAJOR with
the owner never consulted, using sanctioned-looking commands, and the guard the
plan added specifically to close this (review MAJOR 4) advertises `PATH` as
covered. This is the same defect class the guard exists for, reachable around
it.

**Directions (either closes it; do both):**

1. Make `_bash_sets_bypass_env_var` recognise the real invocation shape:
   `bash <file>` / `sh <file>` / `. <file>` where the command also carries
   `--project-root` (Layer 1's required flag) or the target-version argument,
   not only a literal script name. A steering var on any command that runs a
   fetched upgrade script must deny.
2. Make the gate independent of a hostile `PATH`: invoke `timeout` and `git` by
   absolute path (resolve once, up front, and fail closed if not found), and
   have `_pick_gate_python`'s `PATH` fallback refuse a `PATH` the caller
   supplied on the command line — or at minimum record in the verdict which
   interpreter/timeout ran so a planted one is visible. The stdout
   `gate-verdict=proceed` check is not a real defence: one `echo` satisfies it.

---

## MAJOR 1: `git checkout` + `hooks-daemon repair` reaches "already installed" and skips the gate

`evaluate_gate` short-circuits to PROCEED when `installed_stamp == target_stamp`
(`upgrade_gate.py:506-525`). An agent can MANUFACTURE that equality with two
unguarded commands and then run the upgrade with the gate silently satisfied.

Probe (`probe_376r_e2e_repair_out.txt`, scenario `repairstamp`): install
v3.66.0; `git -C .claude/hooks-daemon checkout v4.0.0`; `hooks-daemon repair`
(rebuilds the venv for whatever is checked out and stamps `.daemon-version` =
`v4.0.0`); `git checkout v3.66.0`; then `upgrade … v4.0.0`. The gate reports
`Installed version: 4.0.0 (from the venv stamp)` and
`v4.0.0 is already installed: nothing new to read or approve` — a MAJOR
deployed, gate satisfied, no approval.

Neither `git -C <daemon> checkout <tag>` nor `hooks-daemon repair` is guarded
(`probe_376r_guard_out.txt`: both `allow`). `repair` writes the stamp
legitimately (`scripts/venv_bootstrap.sh:251` builds `ensure_venv_locked "v$version"`), so the stamp-forgery guard (which covers only Write/touch/cp of
`.daemon-version`) does not apply. The checkout also puts the daemon on the new
source immediately, so this is less "sneak a deploy past the gate" and more
"perform the upgrade by hand and then have the gate rubber-stamp it" — but the
gate's whole purpose is that a MAJOR reaches the owner, and this path never
does.

Direction: the already-installed short-circuit trusts the stamp as proof the
transition was gated. It was not. Either drop the fast PROCEED for an
escalation-worthy target (still run the escalation check even when
installed==target), or have the gate record, at approval time, that THIS
from→to was approved, and treat a stamp with no matching approval record as a
range to re-evaluate rather than as "done."

---

## MINOR (from the docs fork; verified against code)

- **D1 (docs half of BLOCKER 1).** `LLM-UPDATE.md:212-213`, release note 67 and
  `HANDLER_REFERENCE.md:1061` claim blanket denial of steering vars "on an
  upgrade command"; the recommended `bash "$tmp"` route is not covered. Fix the
  guard (BLOCKER 1) and/or stop claiming blanket denial.
- **D2.** `LLM-UPDATE.md:217-218`, `truth-changes/v3.67.0.yaml`,
  `pre-upgrade-tasks/README.md:11` and release note 60 say a stop always
  restores the checkout. `abort_before_deploy` (`upgrade_version.sh:280-292`)
  leaves the dir on the target when the installed version cannot be told
  (self-install, direct Layer 2) or the `reset` fails. Add "when the installed
  version can be told."
- **D3.** `LLM-UPDATE.md:238-239` files every exit 1 as a daemon bug. Exit 1
  also means no Python 3.11+ for the gate (`upgrade_version.sh:379-381`, the
  user's job) or a failed restore (`:292`), and the 300 s cap applies only when
  `timeout` exists (`:405`). List the causes and who acts.
- **D4.** "An upgrade needing `HOOKS_DAEMON_PYTHON` must be run by the user" is
  stated in LLM-UPDATE and release note 67 but missing from the skill's
  `upgrade.md` (the procedure agents follow), and `python_discovery.sh:272,278`
  still tells the reader to set the variable with no "ask the user."
- **D5.** LLM-UPDATE's "Standard Upgrade Process" block ends with `rm …/upgrade.sh` and never mentions the exit 3/4 stop or the
  `--skip-reading-confirmation=<digest>` re-run (explained ~60 lines later), so
  an agent running the block as written deletes the script the re-run needs.
- **D6.** `v3.63.0-to-v3.64.0/pre-upgrade-tasks/01-…:42` says a project with no
  `level` hit may "acknowledge," but the task is `critical`: any hit escalates
  to exit 4 (owner), and the same file's `:58-62` say so — a self-contradiction.
  Its Detect pattern `plan[-_]qa\b[^\n]*--json` also matches already-migrated
  and unaffected `plan-qa --json` sites, so they hit the owner on every crossing
  of v3.64.0. Reword; state that even a false positive needs owner approval.
- **D7.** The approval command the gate's stop prints "from any installed
  version" runs bare `python3` (`upgrade_gate.py:636-640`), which fails where the
  default `python3` is 3.9 — the very hosts `HOOKS_DAEMON_PYTHON` exists for.
  Print a discovered 3.11+ interpreter or say "a Python 3.11+."
- **D8.** `upgrade-template/README.md:103-135` still has the agent `cd .claude/hooks-daemon && git checkout vX.Z` (Option A) — contradicting
  LLM-UPDATE step 2 ("Do NOT check anything out") and denied by R-DAEMON-DIR-CD
  — and Option B admits "there is no clone to read it from" but gives no working
  command.

## NIT

- **N1.** Seven release-notes callouts from one plan (55,56,60,61,62,64,67);
  `release-notes/README.md:3` says one short callout per plan. Callout 67 is
  ~9 sentences. Not enforced by the holding-area test. (Numbering is fixed at
  integration — ignore.)
- **N2.** Callout 56's filename slug does not match its title.
- **N3.** `upgrade.md` step 6 runs `check-post-upgrade-tasks` without
  `--project-root` while LLM-UPDATE and the README pass it (auto-detect works,
  forms inconsistent); `LLM-UPDATE.md:90` still calls Layer 1 "~130 lines" (it
  is ~1032); `pre-upgrade-tasks/README.md:9` says "Every Layer 1 upgrade runs
  it" (a direct Layer 2 call runs it too); the v3.64 task's `:75` suggests
  `git checkout -- <file>`, denied by R-GIT-CHECKOUT-DISCARD in a client.
- **N4.** The approval phrase with an unreadable FROM reads `approve upgrade from vunknown to vX` (confirmed live in `probe_376r_runs/ptyapprove/`); the
  docs only ever show `v<installed>`. Cosmetic, but a human is asked to type
  `vunknown`.
- **N5.** PLAN.md Overview / Tasks 1.1 & 4.2 cite pre-branch line numbers
  (`upgrade.sh:550`, `:608-629`, `upgrade_version.sh:733-861`/`:808`,
  `upgrade_compatibility.py:351-373`) that no longer match the files.

---

## What holds (verified, not assumed)

**The gate and guard, on the guarded paths.**

- Exit codes: 3 acknowledge, 4 owner, 1 crash/timeout/no-python; no metadata on
  a stop (`upgrade_version.sh:204-209,414-434`). Stop text verbatim.
- The gate does NOT run on `HOOKS_DAEMON_PYTHON` and does NOT read the installed
  version from `HOOKS_DAEMON_VENV_PATH`: `_pick_gate_python` and the
  `INSTALLED_VENV_PYTHON` block (`:339-349`, `:542-559`) unset both and require
  the venv to be under `<daemon>/untracked/venv-*` by physical path.
  `probe_376r_runs/*/0-install-cur` and the `faketimeout`/`docmarker`/`pth`
  runs confirm the interpreter override is neutralised.
- A forged `HOOKS-DAEMON.md` marker is honoured — but only as the FROM version,
  so it makes the gate STRICTER (an unknown range escalates to the owner). From
  an installed state it just reports the real installed version
  (`probe_376r_runs/docmarker/`). Not an escalation bypass on its own.
- A `.pth` planted in the installed venv's site-packages does NOT reach the
  gate: it runs under `-I` (`upgrade_version.sh:403`), which drops
  site-packages, and on a stampless fresh clone there is no installed venv to
  plant in (`probe_376r_runs/pth/`).
- The `approve` path needs a real TTY: piped under `script -qec` it writes the
  marker (`probe_376r_runs/ptyapprove/`, expected — a human at a pseudo-terminal
  is the intended user), and the guard denies an agent running `approve-upgrade`
  or the standalone `approve`, forging the marker, or setting the handoff var
  (`probe_376r_guard_out.txt`: those `DENY`).
- The handoff is PID- and owner-checked and one-shot (`upgrade_version.sh:136-159`);
  an inherited `HOOKS_DAEMON_UPGRADE_HANDOFF` naming another file is ignored.

**resolve_venv.sh N37** (`probe_376r_resolve_venv_out.txt`):

- `_rv_is_own_venv_python` is sound against a trailing slash (still cached, own
  venv), `..`/`.` in a planted entry (rejected → re-resolves, does not serve
  it), a foreign or symlinked `venv-evil` entry (rejected), and a second line in
  the cache (the extra line is ignored; the first, own-venv line is served). A
  daemon dir reached via a symlink still caches and hits.
- A doubled slash (`…//daemon`) and a relative `.` daemon-dir never cache (the
  path does not match the `venv-` prefix literally) — a latency-only miss, not a
  wrong interpreter; acceptable.
- Hot path: 20 cache hits median 8.2 ms / p90 8.9 ms (well under the \<5 ms
  Python-spawn-avoided budget once the file cache is warm; the first, cold
  resolve is ~5 s because the probe fixture runs the real paths.py). An override
  call never caches and never reads the cache (median 94 ms), so an override
  cannot answer a later un-overridden call — the N37 fix is correct and the
  ledger write-up matches.

**Merge / manifests / QA integrity.**

- `cli.py` is pure insertion (`git diff … cli.py` = +177, 0 removed); all seven
  `cron-pause`/`cron-resume` occurrences preserved (7 on both sides);
  `check-post-upgrade-tasks` and `approve-upgrade` added with correct arg specs.
- Both `v3.67.0` manifests parse (`yaml.safe_load`) and match the released
  schema; the union with main is insertion-only, no main entry dropped or
  reordered (fork-verified against `git show af7b3c07:…`).
- The three removed `error_hiding_exclusions.json` entries correspond to code
  genuinely rewritten with explicit handling (`upgrade.sh:598` rev-parse now
  `> /dev/null ||`; `upgrade_version.sh:932` `run_pre_install_checks` now
  `if ! …; then print_warning`) — not a gate dodged. The only added QA
  annotation is one `# nosec B404` on a test importing `subprocess`
  (`test_upgrade_pre_deploy_phase_runs_on_layer1.py`), justified and standard.
  No `noqa` / `type: ignore` added in the branch.
- All seven release-notes callouts carry `**Plan**: 00376` and pass the
  holding-area test; `test_upgrade_task_schema.py` passes (fork ran both, 60
  tests).

## Bottom line

READY once BLOCKER 1 is closed (guard must cover the documented `bash "$tmp"`
route AND the gate must not resolve its tools through a caller-supplied `PATH`).
MAJOR 1 (checkout+repair → already-installed) should be closed in the same pass,
since it defeats the same approval requirement by a different unguarded route.
The MINORs are doc-truth fixes; none blocks, but D1/D2/D6 assert protections the
code does not deliver and should not ship as written.
