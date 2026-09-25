# Blast-radius policy decision — cross-reference for Plan 00415

The standing policy, its evidence and the reasoning for this plan's
sub-decision live in one place:

[`../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md`](../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md)
— section "Plan 00415 — should the freshness fingerprint cover config?".

## This plan's sub-decision (the load-bearing question, `PLAN.md:79-86`)

**A SEPARATE `config_fingerprint` in the health payload — and the "a consumer
checking only the old one is silently no better off" objection is closed at
the choke point, not by blending digests.** Every consumer in the tree reaches
its verdict through one function, `describe_fingerprint_mismatch`
(`tests/acceptance/conftest.py:108-130`, `daemon/cli.py:1224-1256`,
`scripts/qa/run_smoke_test.sh:73-75`). Change that function to take both
pairs, treat a missing config fingerprint as a staleness RISK exactly as it
already treats a missing source fingerprint
(`daemon/source_fingerprint.py:126-136`), and name which input moved. Every
consumer inherits the fix; Goal 2 (says which drifted) and Goal 3 (the
`.py`-only contract stays honest) both hold. Pin it with a Detector: no module
may read `source_fingerprint` from a health payload without also reading
`config_fingerprint`.

Reasoned leans on the other two questions (not rulings): hash the **resolved
model** under a canonical serialisation, with cross-process determinism proved
before shipping; mix a `loaded` / `absent` / `invalid` discriminator into the
hashed input so a malformed config and no config do not hash alike.

Blast radius: a correctness fix to a verdict, shipped on with no flag —
clients gain an additive payload field and a `check-source-fresh` that tells
the truth after a config edit.

**Human gate: none.** Task 1.1 can be closed by recording the linked document
as the pick.
