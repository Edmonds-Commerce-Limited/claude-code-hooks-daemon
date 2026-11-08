## 23:32 · action · —   — Task 4.2: actions pinned to full SHAs

Task 4.2 done. Every external `uses:` in `.github/` (28 lines across qa.yml, test-shards.yml, release-gate.yml, release-assets.yml and the setup-env composite action) is pinned to the commit its floating tag pointed to on 7 November 2026, with the exact release in a trailing comment: checkout v4.4.0, upload-artifact v4.6.2, download-artifact v4.3.0, setup-python v5.6.0, cache v4.3.0, attest-build-provenance v2.4.0. Behaviour is unchanged; Dependabot's github-actions entry (Task 4.1) now proposes SHA bumps. Local `./` references are this repository's own code and stay unpinned.

Red first: `tests/integration/test_ci_actions_pinned.py` failed 28 (one per line), then passed 30 after the pins.

Landed directly on main: the branch WIP cap was full (Phase 3 of Plan 00571 holds the slots), and a pin to the same commit as the tag is not a behaviour change, so main's own CI run is the check. The open Dependabot PR #181 (major bumps to checkout v7 and others) is left for Dependabot to rebase onto the pinned form; it is a version upgrade decision, not part of this task.

Remaining in this plan: Task 3.3 (non-blocking arm64 test leg) and the measured success criteria.
