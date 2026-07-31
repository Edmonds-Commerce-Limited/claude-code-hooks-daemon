# AUDIT v1 — `mkplan.bash` (candidate baseline)

**Audited**: 2026-06-19
**Method**: shellcheck (static) + empirical execution of the verbatim baseline against a
throwaway git repo, exercising happy-path, hostile inputs, guard paths, symlink deployment
variants, and concurrency. Daemon-integration reasoned against Plan 00112 (git-anchored
counter) + observed live counter behaviour in this workspace.
**Verdict**: **NOT ready to distribute.** One CRITICAL concurrency defect (duplicate plan
numbers under parallel use) and one HIGH deployment defect (symlink mis-location) must be
fixed first. Name-validation and the drift/bootstrap logic are genuinely robust.

---

## Severity-ranked findings

### CRITICAL

#### C1 — Concurrent invocations produce DUPLICATE plan numbers

**Proven.** Eight parallel invocations starting from counter `0` produced **five folders all
numbered `00001`** (`00001-race-4` … `00001-race-8`), final counter `1`, and three runs
crashed with `exit 1` / `exit 255`.

Root cause: the critical section is

```
read counter → next=counter+1 → mkdir "NNNNN-<name>" → write counter=next
```

with **no mutual exclusion**. The earlier assumption that `mkdir "$target"` self-serialises is
**false**: each invocation has a *distinct* name, so the target paths differ
(`00001-race-4` vs `00001-race-5`) and `mkdir` never collides. All eight read the same
counter, all compute `1`, all create a *different* `00001-*` folder, all write counter `1`.
The concurrent `git config` writes also contend on `.git/config.lock`, producing the
hard `exit 1`/`255` crashes.

This is precisely the duplicate-number class the git-anchored counter (Plan 00112) exists to
prevent. Two agents in one container, or an agent + a human, creating plans at the same time
will collide.

**Fix**: wrap the entire resolve→collision-check→`mkdir`→counter-write section in an
advisory `flock` on a lock file in the plan dir (e.g. `.mkplan.lock`). This serialises the
read-modify-write and also removes the `config.lock` contention. (Mirrors the deferred Plan
00100 Phase 4 "flock concurrency" work.) Provide a graceful path when `flock` is absent
(macOS lacks `flock(1)` by default) — fall back to a `mkdir`-based lock or `set -o noclobber`.

---

### HIGH

#### H1 — Reverse-symlink deployment scaffolds plans in the WRONG directory

**Proven.** With the real script at `tools/mkplan.bash` and a symlink at
`CLAUDE/Plan/mkplan`, running the symlink created the plan at **`tools/00001-where-does-this-land/`**,
not under `CLAUDE/Plan/`. The `BASH_SOURCE` loop resolves the final symlink to the real file,
so `plan_dir` becomes the *real script's* directory. The header comment calling this
"symlink-safe" is misleading: it is symlink-*resolving*, which defeats the natural packaging
move of symlinking one shared script into each project's plan dir.

The forward case (real file in plan dir, convenience symlink in `bin/`) works correctly (S1).

**Fix options** (decide in Phase 4): (a) resolve only intermediate symlinks but treat the
**final** invocation path's directory as the plan dir; or (b) keep resolution but document
loudly that the *real file* must live in the plan dir, and have the installer copy (not
symlink) it. Recommend (a) — it makes both deploy styles correct and matches user intuition
("the plan appears next to the command I ran").

#### H2 — Script does not update the README index (workflow gap for agents)

The project convention (and `CLAUDE/Plan/CLAUDE.md`) requires every new plan to get an
"Active Plans" row in `README.md`. The script only scaffolds the folder and *prints a
reminder*. A human reads the reminder; an **agent** that shells out and moves on will leave a
stale index. Either the script should offer to append a stub row, or the agent-facing
guidance must pair "run mkplan" with "then add the README row" as one atomic instruction.

#### H3 — Distribution mechanics are unspecified (proposal gap)

The script must land in the client's **content** tree (`CLAUDE/Plan/`, or wherever
`track_plans_in_project` points), which is *outside* the daemon-managed `.claude/`. The
installer/upgrade flow must therefore: resolve the configured plan dir (not hardcode
`CLAUDE/Plan/`), deploy idempotently, **never clobber** a client-modified copy on upgrade,
set the exec bit, and decide whether the file is daemon-owned (re-deployed each upgrade) or
seeded-once. None of this is defined yet.

---

### MEDIUM

#### M1 — Guidance collision with `plan_number_helper`

The daemon already instructs agents: read `hooksdaemon.latestPlanNumber` and add 1; do NOT
scan with `ls`/`find`. Promoting the script adds a *second* method. (During this audit the
handler even blocked the auditor's `ls … | grep '^[0-9]'`.) The agent-facing surface must
present **one** coherent path, or update `plan_number_helper.get_claude_md()` to name the
script as the canonical action with "read the counter" as the fallback.

#### M2 — Counter write is `set`, not high-water-mark `max()`

The daemon (Plan 00112) writes `max(counter, N)`; the script writes `counter = next`
unconditionally. Monotonic in isolation, but it is the lost-update half of C1 and a
divergence from the documented daemon semantics. After the C1 flock fix, prefer
`max(existing, next)` for symmetry and defence-in-depth.

#### M3 — `mkdir` raw error on same-name collision / re-run

If `NNNNN-<name>` already exists (re-run with the same name, or a same-name race), `mkdir`
fails under `set -e` with a raw shell error rather than the friendly `die` style used
everywhere else. Use `mkdir` failure → `die` with guidance.

#### M4 — Scaffolded `PLAN.md` is an unvalidated write path

Writing via heredoc (bash) deliberately bypasses the Write-tool hooks (this is what avoids
daemon double-increment — good). Side effect: the scaffolded content skips
`validate_instruction_content` / markdown formatting. Low risk because the template is fixed
and trusted, but note it: any future template change ships unchecked.

---

### LOW

- **L1** — Title is not Title-Cased (`first plan` vs the repo's `First Plan` headers). Cosmetic.
- **L2** — Plans > `99999` break the `^[0-9]{1,5}-` rescan regex (YAGNI; note only).
- **L3** — `git rev-parse` / `git config` emit their own stderr before `die`, adding noise to
  the not-a-repo / missing-key messages.
- **L4** — The "counter drift" error also fires for an ordinary "next number already taken"
  case (D3); the wording may read as corruption when it is a normal gap. Consider softening.

---

## Verified robust (passed hostile testing)

- **Name validation**: path traversal (`../../etc/evil`), command injection (`foo; rm -rf`),
  `$()`/backtick injection, slashes, leading digit, empty, whitespace-only, unicode/emoji —
  **all rejected**; no injected command executed (no `PWNED` files).
- **Drift guard**: refuses when the git counter is behind the disk, with an actionable
  reconcile command.
- **Bootstrap**: filesystem high-water-mark correctly includes `Completed/NNNNN-*` (2-level scan).
- **Gap**: counter ahead of disk yields the counter's next value (intended, monotonic).
- **cwd-independence**: forward-symlink + run-from-`/tmp` both scaffold in the correct plan dir.
- **Static**: `shellcheck` clean; constructs are bash-3.2 / BSD-safe (no `readlink -f`, no
  GNU-only `stat`/`date` flags) — consistent with the macOS fixes in Plans 00122/00123.

---

## Fix plan for v2 (this iteration)

Apply now, then re-run the full empirical suite:

1. **C1** — `flock` the critical section, with a `flock`-absent fallback (CRITICAL).
2. **H1** — derive `plan_dir` from the invocation path's directory so a symlink in the plan
   dir scaffolds there (HIGH).
3. **M2** — high-water-mark counter write (`max`).
4. **M3** — friendly `die` on `mkdir` failure.

H2/H3/M1 are **proposal/distribution** decisions → Phase 4, not script edits.
L1–L4 deferred unless trivially bundled.
