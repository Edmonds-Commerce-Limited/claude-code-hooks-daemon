# Proposal Audit — distributing `mkplan.bash` + wiring hooks + guiding agents

**Audited**: 2026-06-19
**Scope**: the three legs of the proposal that are NOT script-internal — distribution (H3),
README/workflow integration (H2), and agent guidance / hook wiring (M1). Grounded in the
actual daemon code, not assumptions.

---

## Evidence gathered from the codebase

| Fact                                                                                                                                                             | Location                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Plan dir is **configurable**: `track_plans_in_project` (default `CLAUDE/Plan`)                                                                                   | `config/models.py:388`; read by `markdown_organization.py:263`, `validate_plan_number.py`, `plan_number_helper.py` |
| Installer **already bootstraps the client plan dir** idempotently (creates `CLAUDE/Plan/`, `Completed/`, `README.md` + `CLAUDE.md`, skip-if-exists)              | `install/plan_workflow.py::bootstrap_plan_workflow()` (l.98–144)                                                   |
| …but that bootstrap **hardcodes** `_PLAN_DIR_NAME = "CLAUDE/Plan"` (l.15) — it does NOT honour `track_plans_in_project`                                          | `install/plan_workflow.py:15`                                                                                      |
| Daemon's Python numbering logic the script must mirror: `counter+1` when set, else bootstrap-from-scan + seed; `record_plan_allocation` writes `max(current, N)` | `handlers/utils/plan_numbering.py:152–198`                                                                         |
| Current agent guidance: "read `git config --local hooksdaemon.latestPlanNumber`, add 1; do NOT scan with `ls`/`find`"                                            | `plan_number_helper.py:173–181` + `get_claude_md()`                                                                |
| Deploy precedents into `.claude/` (re-deployed each upgrade): hooks, slash commands, skills                                                                      | `scripts/install/hooks_deploy.sh`, `slash_commands.sh`; `install/skills.py`                                        |

**Script-vs-daemon parity confirmed**: the v2 bash logic matches the Python SSOT
(`hooksdaemon.latestPlanNumber`, `counter+1`, bootstrap-from-scan, `max()` write, enclosing-repo
resolution). One *intentional* divergence: the daemon trusts `counter+1` even if the disk holds
a higher number; the script **refuses on that drift** with a reconcile hint. The script is the
stricter (safer) of the two — acceptable, and arguably the daemon should adopt the same guard.

---

## H3 — Distribution mechanism — DECISION

**Deploy `mkplan.bash` inside `bootstrap_plan_workflow()`**, alongside the README/CLAUDE.md it
already writes. Rationale: that function is the one place the installer already touches the
client *content* tree (`CLAUDE/Plan/`), already idempotent, already runs on install + upgrade.

Deployment policy — **differs from the README**:

- `README.md` / `CLAUDE.md` are **client content** → skip-if-exists (never clobber).
- `mkplan.bash` is **daemon-owned tooling** → **overwrite on every upgrade** (like the hook
  wrappers / skill scripts) so audit fixes (e.g. the C1 lock) actually reach existing installs.
  A client who forks it is overwritten — acceptable for a daemon-owned helper; document it.
- Set the exec bit (`0o755`) on deploy.

**Sub-finding (pre-existing bug to fix as part of this work)**: `bootstrap_plan_workflow`
hardcodes `CLAUDE/Plan`. If a project sets `track_plans_in_project` to a different path, the
bootstrap writes to the wrong place AND `mkplan.bash` would be deployed to the wrong dir. The
deploy must resolve the **configured** plan dir. This is a real DRY/SSOT violation independent
of this script and should be threaded through (the config value is available at install time).

**Self-install caveat**: in THIS repo the script is committed at `CLAUDE/Plan/mkplan.bash`
(tracked source), not installer-deployed. The installer path applies to *client* projects.

---

## H2 — README index not updated — DECISION

**Do NOT make the script edit `README.md`.** Appending a correct, well-placed "Active Plans"
row (right section, right summary) is a judgement task; a bash heredoc would produce a brittle,
often-wrong stub and fight the markdown table formatter. Instead:

- The script's existing "Next steps" reminder already tells the human/agent to add the row.
- Strengthen the **agent** guidance (M1) so "run mkplan → fill PLAN.md → add the README row" is
  one instruction. The README edit is exactly the kind of contextual write an agent does well
  with the Edit tool, and it then passes through `markdown_organization` + the table formatter.

Accepted limitation: a human who ignores the reminder leaves a stale index — same as today's
manual flow. No regression.

---

## M1 — Agent guidance / hook wiring — DECISION

**One coherent message, no second method.** Update `plan_number_helper.get_claude_md()` (and the
generated `<hooksdaemon>` block) so the canonical action is:

> To create a plan, run `<plan-dir>/mkplan.bash "kebab-name"` — it reads the same
> `hooksdaemon.latestPlanNumber` counter, takes a lock, and scaffolds the folder + `PLAN.md`
> atomically. If you only need the *number* (not a folder), read the counter and add 1.

This keeps the counter as the single source of truth, demotes "read counter +1" to the
number-only fallback, and never tells agents to `ls`/scan. No new handler is required — this is
a guidance-text change on an existing handler, so it stays DRY and within the established
surface. (Note the irony surfaced during the audit: `plan_number_helper` *blocked the auditor's
own* `ls … | grep '^[0-9]'` — evidence the interception works and that a competing method would
be friction.)

**No new hook needed.** The script deliberately writes via bash (`mkdir`/`cat`), so it bypasses
the Write-tool path and the daemon never double-increments. The only "wiring" is the guidance
text + the deploy step. Confirmed safe against the live daemon (writing a PLAN.md via the Write
tool DID bump the counter 129→130 this session; the script's bash writes do not).

---

## Net recommendation

The **script** (v2) is sound and safe to distribute. The **proposal** is viable with three
follow-up work items, none of which block the script audit:

1. Deploy in `bootstrap_plan_workflow` with overwrite-on-upgrade + exec bit, AND fix the
   hardcoded-`CLAUDE/Plan` SSOT bug to honour `track_plans_in_project`.
2. Update `plan_number_helper` guidance to name the script as canonical (number-read as fallback).
3. Leave README updates to the agent/human (guidance, not script automation).

Each is a normal TDD change (installer test for deploy + exec bit + idempotency; handler test
pinning the new guidance text). Recommend spinning them into a follow-up implementation plan
once this audit is accepted — this plan's remit was the hostile audit + refinement, now done.
