# AUDIT v2 — `mkplan.bash` (post-refinement)

**Audited**: 2026-06-19
**Baseline**: `AUDIT-v1.md` findings.
**Method**: re-ran the full empirical suite (shellcheck, hostile names, drift/bootstrap/gap,
symlink variants, **12-way concurrency**, lock cleanup, re-run, help/usage) against the
refined script.
**Verdict**: **CRITICAL and the actionable HIGH script defect resolved.** Remaining open items
are proposal/distribution decisions (H2, H3, M1), addressed in Phase 4 below — not script bugs.

---

## What changed v1 → v2

| Finding                                | Severity | Fix                                                                                                                                                                                                     | Re-verification                                                                                                   |
| -------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| C1 duplicate numbers under concurrency | CRITICAL | Portable atomic-`mkdir` lock (`.mkplan.lock`) around the whole resolve→create→counter critical section; captured-stderr retry (no `2>/dev/null`); EXIT/INT/TERM trap releases only a lock this PID owns | **12 concurrent runs → `00001`–`00012`, 12 distinct, counter=12, zero stale lock.** (v1 produced five `00001-*`.) |
| H1 reverse-symlink mis-location        | HIGH     | `MKPLAN_PLAN_DIR` override + honest "deployment contract" header (real file lives in plan dir; convenience symlink AT it works; symlink INTO plan dir needs the override)                               | Override lands plan in `CLAUDE/Plan/`; documented default lands by the real file. Both behave as documented.      |
| M2 `set` vs `max()` counter            | MEDIUM   | High-water-mark write `max(counter, next)` mirroring Plan 00112                                                                                                                                         | Counter advances monotonically under the lock.                                                                    |
| M3 raw `mkdir` error                   | MEDIUM   | \`mkdir …                                                                                                                                                                                               |                                                                                                                   |

## Regression sweep (all still pass)

- Hostile names (`foo; rm -rf x`, traversal, `$()`/backtick, slash, leading digit, empty,
  unicode) — rejected, no execution.
- Drift guard — refuses when counter < disk; softened wording (no longer says "drift", says
  "counter is behind the highest plan on disk") with the reconcile command (L4 addressed).
- Bootstrap includes `Completed/NNNNN-*`; gap (counter ahead) intended.
- `.mkplan.lock` dotfile is NOT matched by the `*/` plan globs — proven implicitly by the
  clean `00001`–`00012` numbering with the lock dir present throughout the concurrent run.
- `shellcheck` clean; `-h`/`--help` exits 0; no-arg prints usage + non-zero.

## Still open — but NOT script bugs (Phase 4 proposal decisions)

- **H2** — README index not updated by the script.
- **H3** — distribution mechanics (where/how the installer deploys it).
- **M1** — agent-guidance collision with `plan_number_helper`.
- **M4** (LOW-risk note) — scaffolded `PLAN.md` is an unvalidated bash-heredoc write (by
  design, to dodge the double-increment); fixed template, so accepted.
- **L1/L2/L3** — title not Title-Cased; >99999 regex; git's own stderr before `die`
  (cannot `2>/dev/null`-suppress L3 without tripping the error-hiding blocker — accepted).

## Residual risk on the lock (documented, accepted)

A process `kill -9`'d between `mkdir lock` and `rmdir lock` leaves a stale `.mkplan.lock`.
Next run spins `LOCK_MAX_ATTEMPTS` (~10s) then dies with an explicit "remove the directory if
no other mkplan is running" message. This is the correct fail-loud behaviour; a TTL/auto-break
would risk two runners colliding. No code change.
