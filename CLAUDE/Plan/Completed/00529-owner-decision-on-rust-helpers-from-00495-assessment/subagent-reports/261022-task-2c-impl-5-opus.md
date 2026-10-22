# Plan 00529 Task 2c, part 5: docs, release note and targeted QA

Written by the coordinator from the branch history and the QA output. The part-5 agent committed its work but stopped
before writing this report.

## Delivered

- `fd933ffee`: docs. A missing or broken relay binary falls through loudly to the bash path and is repaired at
  session start (`CLAUDE/Worktree.md` and the transport docs).
- `4b71e3d6f`: release note 019, "a broken relay binary never runs a tool call unguarded".
- `610146d01`: the relay repair lock test uses named timeouts instead of magic values. This fixes the first QA run's
  `magic_values` finding.
- Task 2c is ticked in PLAN.md.

## QA

- First run (`untracked/scratch/qa-529-final.txt`): 35/40, with `magic_values` (2), advisory docs/plan QA, and
  `changed_tests` reporting 0 run.
- Re-run on `610146d01` (`untracked/scratch/qa-529-final-2.txt`): `QA: 36/40 PASSED, 2/40 FAILED, 2/40 NOT MEANINGFUL`. The two failures are advisory only: a PLAN.md link to this report, which did not exist until now.

## For the full gate

Targeted QA could not map tests to these files, so main CI's full run must cover them: `init.sh`, the generated
forwarders, `protocol.py`, `relay_deploy.py`, `transport_toggle.py` and `tests/conftest.py` (the step-2 fixture that
stops the relay checker spawning a real build under pytest).
