# Adversarial audit: MERGE-SPEC.md (Plan 00176 Task 1.3)

Scope: the DESIGN in `CLAUDE/Plan/00176-settings-json-merge-preserve-on-upgrade/MERGE-SPEC.md`
as of the version ending at line 163. Nothing is implemented, so every finding is
a spec defect: a state the spec does not cover, or covers with a rule that loses
data when followed literally.

Evidence scripts kept alongside this report:

- `subagent-reports/probe_fragment.py` — classifies real command strings with the
  real `_DAEMON_WRAPPER_FRAGMENT` and the real migrator.
- `subagent-reports/probe_merge_rule.py` — implements Q2's rule literally and runs
  six adversarial settings documents through it, then through the real validators.

Run with `./.venv/bin/python <path>` from the repo root.

Sound, in one line each: Q1's split (dedicated command, not a YAML-loader swap) is
correct and the reason given is the right one. Q5 is genuinely moot. The
"identified by command, not by position" invariant (`MERGE-SPEC.md:160-162`) is
right. The "copy the client document and edit it, never build a daemon document
and graft client keys on" direction-of-copy invariant (`:156-159`) is the single
best thing in the spec and every finding below is a place where the spec's own
rules break it.

---

## CRITICAL

### C1. The three-way rule has no old-default baseline for settings.json, on the path every client runs (Confidence: 95%)

**Location:** `MERGE-SPEC.md:150` (the Recommended-default row); `MERGE-SPEC.md:26-29`

**Problem:** The rule needs (old-default, new-default, user). Nothing produces the
old default for `settings.json`.

- The YAML path gets its baseline from a file that exists on the client's disk
  (`.claude/hooks-daemon.yaml.example`) or from a Layer 1 handover
  (`scripts/upgrade.sh:331-340`, exported as `HOOKS_DAEMON_OLD_DEFAULT_CONFIG`).
- There is no `settings.json.example` anywhere in the tree, and the client's
  `.claude/settings.json` is the USER copy, not a baseline.
- The only other candidate is `$DAEMON_DIR/.claude/settings.json`, and by the time
  either deploy site runs it is already the NEW default: Layer 1 checks out the
  target tag before invoking Layer 2 (`scripts/upgrade_version.sh:272-278` states
  this outright, and it is why `ROLLBACK_REF = TARGET_VERSION` on the fast path).

**Bad outcome:** The implementer of Task 2.2 has to invent a fallback, and both
available fallbacks are the bug this plan exists to fix:

- Treat "no baseline" as "preserve the user value": `refreshInterval: 1` (Plan
  00175) never reaches any existing client, forever. That is precisely the
  scenario named in `PLAN.md:27-29`.
- Treat "no baseline" as "take the new default": every accepted default is
  silently overwritten — the clobber, reintroduced under a merge's name.

`config_preserve.sh:135-157` already documents this exact trap for YAML ("Get it
wrong in the 'new default' direction and every accepted default looks deliberate…
That failure is silent and looks exactly like honouring a customisation"). The
spec inherits the trap without inheriting the mitigation.

**Remediation:** Add a Q6 to the spec: "where the old default comes from." Specify
that Layer 1 (`scripts/upgrade.sh`, beside the existing YAML handover at
`:331-340`) captures `git -C "$DAEMON_DIR" show "$ROLLBACK_REF":.claude/settings.json`
into a temp file before checkout and exports it as
`HOOKS_DAEMON_OLD_DEFAULT_SETTINGS` with a matching `_PID`, mirroring
`resolve_old_default_config` / `warn_if_baseline_handover_looks_stale` /
`cleanup_old_default_config` (`config_preserve.sh:166-267`). Then specify the
no-baseline behaviour explicitly and in one direction only: preserve the user
value, never upgrade it, and record it as a reported conflict rather than a silent
choice.

---

### C2. The `/.claude/hooks/` fragment misidentifies client hooks as daemon-owned, and the rule then destroys them (Confidence: 95%)

**Location:** `MERGE-SPEC.md:67-71`, `MERGE-SPEC.md:149`

**Problem:** The fragment is a substring test on a free-form shell command. Four
distinct client-authored shapes match it (verified, `probe_fragment.py`):

| Client command                                                          | Fragment matches |
| ----------------------------------------------------------------------- | ---------------- |
| `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/my-secret-scan`                | yes              |
| `python3 audit.py --wrappers "$CLAUDE_PROJECT_DIR"/.claude/hooks/`       | yes              |
| `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use && bash ci/gate.sh` | yes            |
| `bash "$HOME"/dotfiles/.claude/hooks/lint`                              | yes              |

`.claude/hooks/` is the directory literally named "hooks"; a client putting their
own script there is the obvious thing to do, and this repo's own tree has a
non-forwarder subdirectory in it (`.claude/hooks/handlers/`).

**Evidence** (`probe_merge_rule.py`, cases A and E, run against the real
`HOOK_COMMAND_TEMPLATE` and the real validators):

```
=== A - client script in .claude/hooks/, sibling of the forwarder ===
BEFORE: [... "command": ".../hooks/pre-tool-use" ...], [... "command": ".../hooks/my-secret-scan"]
AFTER:  [... "command": ".../hooks/pre-tool-use" ...], [... "command": ".../hooks/pre-tool-use"]
  validator: PreToolUse has 2 daemon command hooks (expected 1) — likely duplicate registration

=== E - forwarder chained with a client gate ===
BEFORE: "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/pre-tool-use && bash ci/extra-gate.sh"
AFTER:  "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/pre-tool-use"
```

Case A loses the client's security scan AND leaves the daemon forwarder registered
twice, so every `PreToolUse` fires the daemon twice from then on. Case E silently
deletes the client's CI gate. Both are reported as a successful merge.

The root cause is a category error the spec makes explicit at `:68-69`: the
fragment is borrowed from `detect_legacy_hook_commands`
(`utils/hook_registration.py:194`), where its job is ADVISORY — deciding whether to
nag. Repurposing an advisory heuristic as the discriminator for a DESTRUCTIVE
rewrite raises the cost of a false positive from "a spurious warning" to "the
client's hook is gone".

**Remediation:** Replace the substring test with an exact-match identity rule. A
hook is daemon-owned only if its `command`, stripped, equals
`HOOK_COMMAND_TEMPLATE.format(bash_key=...)` for the bash_key of the event it sits
under, OR matches `hook_command_migration.legacy_command_bash_key()`
(`utils/hook_command_migration.py:76-100`), which is already an anchored regex
built for exactly this "is this ours" question and already returns the key needed
to rebuild. Anything else is the client's — including a command that merely
CONTAINS our path. Add the four rows above to Task 2.1's RED tests.

---

### C3. The same fragment MISSES the relative legacy forwarder — the exact shape the spec promises to repair (Confidence: 95%)

**Location:** `MERGE-SPEC.md:61-65` ("a relative path"), `MERGE-SPEC.md:67-71`

**Problem:** `_DAEMON_WRAPPER_FRAGMENT` is `"/.claude/hooks/"` — with a leading
slash. The relative legacy command `.claude/hooks/pre-tool-use` does not contain
it. Verified (`probe_fragment.py`):

```
spec says OURS  migrator sees legacy  truth
False           pre-tool-use          daemon forwarder (relative legacy, install_version.sh fallback)
                                    '.claude/hooks/pre-tool-use'
```

That shape is not hypothetical: `hook_command_migration.py:65-69` records it as
what `scripts/install_version.sh`'s fallback wrote, and calls it "the one install
shape nothing else repairs".

**Bad outcome:** Under the ownership table the entry is classified CLIENT-owned and
therefore "never touched". The upgrade preserves a broken forwarder — a relative
path resolved against the process cwd — forever, while `detect_legacy_hook_commands`
nags about it every session. Confirmed by `probe_merge_rule.py` case C, which shows
the command unchanged after the merge plus both validators complaining. Row three
of the spec's own table (`:57`) is the row the design fails on.

**Remediation:** As C2 — reuse `legacy_command_bash_key`, which matches both the
anchored and the relative legacy patterns (`hook_command_migration.py:70-73`).
State in the spec that the daemon-owned test is the UNION of {canonical current
command} and {`legacy_command_bash_key` non-None}, and add a test asserting
`.claude/hooks/<key>` is repaired.

---

### C4. Headless "exit non-zero" aborts on the one path that has no rollback, and wedges the client permanently (Confidence: 90%)

**Location:** `MERGE-SPEC.md:96-101`

**Problem:** Two separate defects in one rule.

*(a) It aborts a half-applied upgrade with no rollback.* The fast path is, per its
own comment, "the effective single deployment path for every client upgrade"
(`upgrade_version.sh:272-278`). On it, the settings deploy is already gated:

```
# upgrade_version.sh:312-313
deploy_settings_json "$SETTINGS_JSON_SOURCE" "$PROJECT_ROOT/.claude/settings.json" "" \
    || fail_fast "Could not preserve the existing settings.json"
```

`fail_fast` exits non-zero, which fires the EXIT trap — but the trap only rolls
back when `UPGRADE_STARTED = true` (`upgrade_version.sh:161`), and that is set at
`:558`, well after the fast path's `exit 0` at `:444`. `SNAPSHOT_ID` is likewise
still `""` (`:121`, assigned at `:549`). So a non-zero return from the merge on the
fast path leaves: new forwarder scripts already deployed (`:306`), the OLD
settings.json, the daemon NOT restarted (`:422` never reached), no snapshot, and no
rollback. That is exactly the "stale or incomplete hooks block" state the plan's
Goals forbid, produced by the safety rule.

*(b) It is not recoverable without a human, and the spec provides no human.* The
conflict is a pure function of (client file, old default, new default). The rule
explicitly changes none of them. Run N+1 therefore recomputes the identical
conflict and exits non-zero identically, forever. There is no `--accept-merge`, no
"apply the sidecar", no exit code distinguishing "conflict, nothing changed" from
"hard failure", so a CI-driven client is not merely blocked once — it can never
upgrade again, and each attempt re-enters state (a).

**Remediation:** Three changes to the spec's Q3:

1. Move the merge so it runs BEFORE any irreversible deployment on the fast path
   (before `deploy_all_hooks` at `:306`), or make the fast path take the Step 3
   snapshot before it deploys anything. State which.
2. Define distinct exit codes: 0 clean, 2 "conflict — nothing changed, proposal at
   PATH", 1 hard failure. Specify that callers treat 2 as "keep the existing
   settings.json and CONTINUE the upgrade, warning loudly" rather than `fail_fast`,
   since the pre-merge file is a valid, working file.
3. Name the resolution command a headless operator runs to accept a proposal, and
   specify that accepting re-validates against the CURRENT defaults (a stale
   proposal computed against an older new-default must not be blindly copied into
   place).

---

### C5. On fresh install over an existing settings.json, the ownership table drops three shipped daemon defaults (Confidence: 85%)

**Location:** `MERGE-SPEC.md:151` (Client-owned row); `PLAN.md` Task 2.3 (wires the
merge into `install_version.sh` Step 5)

**Problem:** The daemon's shipped `.claude/settings.json` contains four top-level
keys beyond `hooks`: `plansDirectory`, `permissions.deny` (guards `/tmp`,
`/var/tmp`, `/dev/shm`), `statusLine`, and `enableArtifact: false`. The table
classifies `permissions`, `plansDirectory` and "every other top-level key" as
CLIENT-owned, "preserved verbatim, always". Preserving verbatim includes preserving
their ABSENCE.

**Input state:** A project that has used Claude Code before installing the daemon —
i.e. one where Claude Code already created `.claude/settings.json` to record an
approved permission. This is the common case, not the corner case.

**Bad outcome:** After Task 2.3 replaces the `cp` at `install_version.sh:382-396`
with the merge, that project never receives `permissions.deny` (the /tmp write
guard), never receives `enableArtifact: false`, and never receives
`plansDirectory` — whose absence trips the daemon's own `R-MARKDOWN-PLAN-SYNC`
(`PLAN.md:52`). Today's verbatim copy delivers all three. The merge is therefore a
security and correctness REGRESSION for fresh installs, introduced by a rule
written for upgrades.

**Remediation:** Add a fourth ownership class, "seed-if-absent": keys the daemon
delivers when the key is missing and never touches when present —
`permissions.deny` entries (merge by union, not replace), `plansDirectory`,
`enableArtifact`. Specify per key whether the seed applies on fresh install only or
on every run, and state explicitly that `permissions` is a MERGE-by-union target,
not an opaque blob, or a client with their own `permissions.allow` still loses the
daemon's `deny` list.

---

### C6. Endorsing the wholesale replace of a non-dict `hooks` block contradicts the spec's own tiebreak and destroys client hooks (Confidence: 85%)

**Location:** `MERGE-SPEC.md:59` (table row: "`hooks` not a dict → replaced
wholesale ✅") vs `MERGE-SPEC.md:96-101` (escalate, never guess)

**Problem:** `reconcile_settings_hooks` replacing a malformed block is defensible in
a session-time SELF-HEAL that must not crash. It is not defensible in a merge whose
stated tiebreak is "preserve, don't destroy". Verified (`probe_merge_rule.py` case
F): a client whose `hooks` is a LIST loses every hook it contained, and the merge
reports success.

The plausible way to arrive there is a Claude Code schema change or a hand edit —
i.e. precisely the situation where the daemon's model of the file is wrong and
guessing is most expensive.

**Remediation:** Change the row to "escalate". Specify: a `hooks` value that is not
a dict, a top-level document that is not an object, and a file that does not parse
as JSON all take the Q3 non-interactive path (change nothing, write the proposal,
report). Mirror the guards at `utils/settings_repair.py:77-84`. Keep the wholesale
replace only for the genuinely empty case (`hooks` absent).

---

### C7. Four unsynchronised writers of settings.json, no lock, and one of them un-does the merge (Confidence: 85%)

**Location:** `MERGE-SPEC.md` (silent on concurrency and on the session-time writers)

**Problem:** `.claude/settings.json` already has three writers, and the merge is a
fourth. None of them takes a lock (verified: no `flock`/lockfile in
`utils/settings_repair.py`, `utils/hook_command_migration.py` or
`scripts/install/settings_deploy.sh`).

| Writer | Site | Write style |
| ------ | ---- | ----------- |
| SessionStart self-heal (adds missing events) | `utils/settings_repair.py:57-122` (via `handlers/session_start/hook_registration_checker.py:168`) | atomic (`tmp` + `replace` + `copymode`) |
| SessionStart migrator (rewrites legacy commands) | `utils/hook_command_migration.py:258` (via the same handler, `:155`) | **non-atomic `write_text` in place** |
| Upgrade deploy | `scripts/install/settings_deploy.sh:78` | `cp`, non-atomic, **exit status unchecked** |
| `install.py` | `install.py:717-754` | rename-then-write, non-atomic across the pair |

**Input state:** The documented, dogfooded way to run an upgrade is from inside a
Claude Code session in the same project. Any session started during the upgrade
window fires `hook_registration_checker` (it matches on every non-resume session,
`hook_registration_checker.py:122-131`) and writes the file.

**Bad outcomes, all silent:**

- Lost update: the merge reads at T0, the session's repair writes at T1, the merge
  writes its T0-derived result at T2. The session's added registrations vanish;
  both report success. Reverse the order and the client's just-merged
  customisations are reverted.
- Torn read: `hook_command_migration.py:258` writes in place, so a concurrent
  reader (or a crash) can observe a truncated `settings.json`. Claude Code then
  fails to parse settings and EVERY hook goes dark, including the daemon's.
- Defeat-by-reinstall: `install.py:746-752` builds a settings document containing
  only `statusLine` (with no `refreshInterval`) and `hooks`. Running `install.py`
  after a successful merge writes that document over the merged result — a backup
  is taken (`:717-720`), but the live file has lost `permissions`,
  `plansDirectory`, `enableArtifact` and `refreshInterval` again. The merge is only
  as durable as the least careful writer.

**Remediation:** Add a Q7 to the spec: "who may write settings.json, and under what
lock." Specify (a) one advisory lock file, e.g. `.claude/settings.json.lock`, taken
by all four writers with a bounded timeout; (b) that every writer uses the
temp+`replace`+`copymode` pattern already audited in `settings_repair.py:98-113`
(the `copymode` is load-bearing — Plan 00239 — because the target is git-tracked);
(c) that `install.py`'s `create_settings_json` becomes seed-if-absent plus a
reconcile, not a rewrite; and (d) that the merge re-reads and re-validates under
the lock immediately before writing, so a concurrent repair is not silently
dropped.

---

## IMPORTANT

### I1. "Rebuilt from HOOK_COMMAND_TEMPLATE" is ambiguous, and one reading resets a client's timeout (Confidence: 80%)

**Location:** `MERGE-SPEC.md:70-71`, `:149`

**Problem:** `HOOK_COMMAND_TEMPLATE` renders only the command STRING
(`hook_registration.py:335`), whereas the entry builder
`_build_hook_registration` (`:359-367`) produces the whole inner hook —
`{type, command}` plus `timeout: 60` for PreToolUse/PostToolUse only. "Rebuilt from
the template" can mean either. The difference is a client's data:

- Replace the `command` field only: a client's `"timeout": 300` (raised because
  their handlers are slow) survives — confirmed, `probe_merge_rule.py` case B.
- Rebuild the inner hook: that `300` becomes `60`, and any client-added key on the
  inner hook is dropped. Their long-running hook starts timing out after an
  upgrade, with no message.

**Remediation:** State it in one sentence: the merge replaces the `command` STRING
of an identified daemon hook and preserves every other key of that inner hook,
except that a missing `timeout` is ADDED for the events in
`_BASH_KEYS_WITH_TIMEOUT` (`hook_registration.py:342`) and an existing one is never
changed. Add a test for the `timeout: 300` case.

### I2. An entry-level `matcher` neuters a forwarder that the merge then certifies as complete (Confidence: 80%)

**Location:** `MERGE-SPEC.md:149`, and the Goal at `PLAN.md:138-140`

**Problem:** The spec's unit is the inner hook, so an entry-level `matcher` is
outside it and survives. Confirmed (`probe_merge_rule.py` case D): a `PreToolUse`
entry with `"matcher": "Bash"` around the daemon forwarder emerges unchanged, the
wired-set check passes, and `validate_hook_commands`
(`hook_registration.py:236-309`) reports nothing — it never reads `matcher`. Every
non-Bash PreToolUse event is dark, and the upgrade certifies the hooks block
complete.

**Remediation:** Specify that a daemon forwarder must sit in an entry with no
`matcher` (or `matcher: "*"`), that the merge MOVES a matched forwarder into an
unmatched entry of its own rather than deleting the matcher in place (so a client
who deliberately scoped a sibling keeps their scope), and that the case is reported.
Add the same check to `validate_hook_commands` so the session-time audit sees it.

### I3. Duplicate daemon commands within one event are unspecified, and C2's rewrite manufactures them (Confidence: 80%)

**Location:** `MERGE-SPEC.md:67-71`

**Problem:** The rule says every matching inner hook is rebuilt. Two matches in one
event therefore become two byte-identical commands — the double registration
`validate_hook_commands:268-273` exists to flag — and the daemon then runs twice per
event. The spec never says whether the merge collapses duplicates, keeps the first,
or escalates.

**Remediation:** Specify: exactly one daemon command hook per event survives the
merge; a second identified match is removed and the removal reported; matches that
differ in any preserved key (see I1) escalate rather than being silently collapsed.

### I4. `settings.local.json` is ignored, so adding a missing wired event can create double-firing (Confidence: 75%)

**Location:** `MERGE-SPEC.md:39-43` (adds any absent event key)

**Input state:** A client who moved forwarders into `.claude/settings.local.json` —
a misplacement the daemon already detects and advises on
(`detect_local_hooks_misplacement`, `hook_registration.py:117-146`).

**Bad outcome:** The merge sees the event absent from `settings.json`, adds it, and
now the same forwarder is registered in both files. `detect_duplicate_hooks`
(`:85-114`) calls that out: "hook will fire twice". The merge converts a warning
into a live double-execution of every handler on that event, including stateful ones
(counters, cron markers, the failsafe tick).

**Remediation:** Specify that the merge reads `settings.local.json`, and that an
event registered there is reported as a conflict (with the "move it to
settings.json" guidance) instead of being silently duplicated into `settings.json`.

### I5. No rule for an unparseable or non-object client settings.json (Confidence: 80%)

**Location:** `MERGE-SPEC.md` (absent)

**Problem:** A hand-edited file with a trailing comma, a `//` comment, or a BOM does
not parse as JSON. The spec's ownership table presumes a parsed dict and says
nothing about failing to get one. The natural implementation — catch the error and
fall back to the old deploy — is total loss of the client's file's contents.

**Remediation:** Specify: a client file that fails to parse, or parses to a
non-object, takes the Q3 non-interactive path — touch nothing, write the proposed
document alongside, report — and NEVER falls back to the verbatim copy. Mirror
`settings_repair.py:77-84`.

### I6. Atomicity and file mode are unspecified for a git-tracked file (Confidence: 80%)

**Location:** `MERGE-SPEC.md:107-121` (Q4 delegates to `settings_deploy.sh`)

**Problem:** Q4 delegates the WRITE as well as the backup, and
`settings_deploy.sh:78` writes with a plain `cp` whose exit status is not checked;
`print_success "Redeployed settings.json"` and `return 0` follow unconditionally
(`:79-80`). A `cp` that fails part-way (ENOSPC, read-only mount, a signal) leaves a
truncated `settings.json` and reports success — after which Claude Code cannot parse
settings and every hook, daemon included, silently stops. This is the exact
half-written state the spec's tiebreak is supposed to make impossible, sitting
inside the component the spec declares finished.

**Remediation:** Two spec sentences plus one code fix: (a) the merge writes via
temp + `Path.replace` + `shutil.copymode`, per `settings_repair.py:98-113`; (b)
`settings_deploy.sh:78` becomes `if ! cp "$source" "$target"; then print_error …;
return 1; fi`, and the file is written to a temp sibling then `mv`d so an
interrupted deploy cannot truncate the target.

### I7. Q4's "nothing further is owed" is not true of two of the four write sites (Confidence: 80%)

**Location:** `MERGE-SPEC.md:105-126`

**Problem:** Q4 claims `settings_deploy.sh` is "the single deploy path" and that "no
raw `cp "$SETTINGS_JSON_SOURCE"` survives". Both claims are scoped to
`upgrade_version.sh` — which is also all the pinning test checks
(`tests/integration/test_settings_deploy_lib.py:198-200` reads only
`upgrade_version.sh`). The fresh-install site still has its own backup-then-copy
(`install_version.sh:382-396`, raw `cp` at `:390`), and `install.py:717-754` still
rewrites the whole document. Q4's "all three routes now copy before they overwrite"
is about BACKUP; it does not make either site preserve anything, and the merge must
be wired into both or the first re-run undoes it (see C7).

**Remediation:** Correct Q4 to enumerate four sites and their status. Add
`install_version.sh` Step 5 and `install.py` to the merge's wiring in Task 2.3.
Widen `test_no_raw_copy_of_the_settings_source_remains` to `install_version.sh`.

### I8. Backups and the headless proposal file are not gitignored, and never pruned (Confidence: 85%)

**Location:** `MERGE-SPEC.md:96-98` (writes a proposal alongside), `:114-115`
(timestamped `.bak-`)

**Problem:** Verified with `git check-ignore`:

```
.claude/settings.json.bak-20260908-120000     -> NOT ignored
.claude/settings.json.bak.pre-registration-repair -> IGNORED
.claude/settings.json.merged                  -> NOT ignored
```

`.gitignore:129-130` covers `*.bak` and `*.bak.*`; the hyphenated timestamp shape
written by `settings_deploy.sh:67` and `install_version.sh:386` matches neither. So
every differing upgrade drops an untracked file into a tracked directory, with no
retention policy (unlike snapshots, which get `cleanup_old_snapshots … 3`). In CI,
a clean-tree assertion now fails on the upgrade itself; on a workstation the files
accumulate indefinitely, each a full copy of a file that may contain a `permissions`
block.

**Remediation:** Add `.claude/settings.json.bak-*` and the chosen proposal-file name
to the gitignore template (`scripts/install/gitignore.sh`, which currently has no
settings entries at all), and specify a retention rule in the spec: keep the N most
recent settings backups, matching the snapshot policy.

### I9. "Offered on upgrade" is a contract nothing implements (Confidence: 75%)

**Location:** `PLAN.md:139-140` (Goal) vs `MERGE-SPEC.md:83-88` and `:150`

**Problem:** The Goal says recommended defaults are "offered on upgrade". Q3
forbids routine narration, and the three-way rule either silently upgrades the value
or silently preserves it. There is no path in the design on which anything is
offered. The word is doing work no mechanism performs.

**Remediation:** Either delete "offered" from the Goal and state that recommended
defaults are applied silently when the user never diverged, or define the offer
concretely: a one-line advisory naming the key, the old default, the new default and
the command to accept — emitted only when the value was PRESERVED because it
diverged, which is rare enough to satisfy Q3's "worth something only if it is rare".

### I10. Absence semantics for recommended-default keys are undefined (Confidence: 80%)

**Location:** `MERGE-SPEC.md:150`

**Problem:** "User value differing from the old default is preserved" does not say
whether a MISSING key is a differing value. Both readings are live and both are
somebody's bug:

- Missing counts as "differs" → a client who deliberately deleted `statusLine`
  (they use their own, or none) keeps it deleted. Fine — but so does a client
  whose file predates the key, who then never receives the recommended default.
- Missing counts as "not customised" → the deleted `statusLine` is restored on
  every single upgrade, forever, and the client cannot win.

**Remediation:** Specify tri-state handling explicitly, as the YAML path already
does with its `UNSET` sentinel (`install/config_cli.py:34-48`): present-and-equal,
present-and-different, absent. Decide and record that ABSENT means "the user removed
it" only when the old default HAD it (so it is preserved as absent and reported
once), and means "never seeded" when the old default lacked it (so it is added).

### I11. A user who deliberately pins the old default is silently upgraded, and the spec does not admit it (Confidence: 75%)

**Location:** `MERGE-SPEC.md:150`

**Problem:** Inherent to three-way merges, but the spec claims a tiebreak of
"preserve, don't destroy" and this is the case where it silently does the opposite.
Input state: old default `refreshInterval: 1`; client explicitly pins `1` in code
review because they never want it to change; new default becomes `5`. The merge
cannot tell the pin from an untouched default and writes `5`.

**Remediation:** Name the limitation in the spec rather than leaving it implicit, and
specify the one mitigation available: any recommended-default key whose value the
merge CHANGES is listed in the upgrade output with the before/after and the backup
path — a report of a change made, not a prompt, so it does not violate Q3.

---

## SUGGESTIONS

- `MERGE-SPEC.md:149` — the ownership table's first row is scoped to
  `hooks[event]`, but the daemon's `statusLine.command` also contains
  `/.claude/hooks/` (see `.claude/settings.json`). State the scope restriction
  explicitly so an implementation that walks the whole document cannot classify
  `statusLine` as a hooks entry.
- `MERGE-SPEC.md:150` — `statusLine.type` is in neither the recommended-default nor
  the daemon-owned class, so a client with `"type": "command"` removed keeps a
  broken status line no upgrade repairs. Add it, or say the whole `statusLine`
  block is the unit.
- `MERGE-SPEC.md:39-49` — nothing covers a registration for an event that is no
  longer wired (removed from `wired_event_metas()`). No forwarder pruning exists in
  `scripts/install/hooks_deploy.sh` today, so the harm is currently latent, but the
  merge should report an orphan rather than leave a registration pointing at a
  script that a future prune deletes.
- `MERGE-SPEC.md:77-79` — the claim that the merge "becomes a fourth caller" of
  `HOOK_COMMAND_TEMPLATE` is not quite right: `install.py:733-734` re-implements the
  string as a literal rather than calling the template, and is only held in step by
  a drift test. Worth a sentence so the implementer does not go looking for a call
  that is not there.
- `.claude/settings.json` is git-TRACKED in this repo and in clients
  (`scripts/install/gitignore.sh` has no settings entries). A merge therefore writes
  into version control: two developers upgrading on different machines each produce
  a different merged file, and the resulting conflicts are in a file that governs
  whether hooks run at all. The spec should say who owns the committed copy and
  whether the merge is expected to be deterministic across machines (it is not, if
  the baseline resolution of C1 depends on local state).

---

## Verdict

REQUEST CHANGES. The direction-of-copy invariant is right and the Q1 split is
right, but the two load-bearing mechanisms are not implementable as written: the
three-way rule has no baseline to work from (C1), and the daemon-owned
discriminator both destroys client hooks it should not touch (C2) and misses the
stale forwarder shape it was chosen to repair (C3). C4 turns the safety fallback
into a permanent upgrade block on the path every client uses, and C5 makes the
merge a security regression for fresh installs. Phase 2 should not start against
this version of the spec.
