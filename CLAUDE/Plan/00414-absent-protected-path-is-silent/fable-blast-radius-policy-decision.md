# Blast-radius policy decision — cross-reference for Plan 00414

The standing policy, its evidence and the reasoning for this plan's
sub-decision live in one place:

[`../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md`](../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md)
— section "Plan 00414 — an absent protected path is silent".

## This plan's sub-decisions

**Q1 (`PLAN.md:65-69`) — always, or only against an explicit declaration?**
Neither as posed. Report absence for a path that a live-enabled guard
**resolves and would consume** — today, `sensitive_content`'s word-list path,
whether set explicitly or inherited as the default. A protected *glob* has no
"absent" state, so "always" is unimplementable for most of the list; and
"only when explicitly declared" would have missed the motivating case, because
this repository does not set `secret_word_list_path`
(`.claude/hooks-daemon.yaml:186-190`) — the default path is what was absent.
This is the register's `absence-indistinguishable-from-clean` class, instance
F-PRIV-4.

**Q2 (`PLAN.md:71-75`) — once per checkout, or every session?** Every **new**
session while the path stays absent; silent on resume; silent once present;
and silent once a project declares "no list, on purpose" in config. That is
what `deployed_artefact_drift`, `config_optimisation_reminder`,
`guard_config_drift` and `lsp_noise_checker` all do; no SessionStart advisory
in the tree uses a once-per-checkout marker, and the plan's own objection to
one stands. The explicit "none" declaration is the acknowledge route that keeps
the every-session form from becoming the noise failure in Goal 3.

Design note carried over: put the finding in `secret_file_hygiene_checker` as
a "declared but absent" section rather than a new handler; `Path.exists()` is
metadata and keeps the never-open-the-file contract.

**Human gate: none.** Task 1.1 can be closed by recording the linked document
as the settlement of both questions.
