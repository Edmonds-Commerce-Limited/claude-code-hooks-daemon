## 12:06 · finding · —   — Drift self-heal demonstrated; a missed DBF instance found at the current venv key

The drift self-heal demonstration (`subagent-reports/261031-drift-self-heal-demo.md`) passes the success criterion for the incident's shape. A py311-named venv whose `bin/python` now runs 3.13 is rejected by the hook. The hook prints the Task 2.4 diagnosis and builds a fresh py313 venv in about 4 s. `.venv-bootstrap.result` records success, and the next hook starts the daemon. No human command is needed.

It also found a lockout: drift that sits at the CURRENT venv key, meaning a py313-named venv whose `pyvenv.cfg` records 3.11. `_venv_is_fresh` (`scripts/install/venv.sh`) trusts the lock hash or stamp, so the build reuses the venv. The success judge then fails, a `.failed` marker blocks retries, and `repair` fails the same way.

This is an instance of the DBF class under cause (d), freshness by lock hash or stamp only. Its Python twin `_cli_check_venv_fresh` was fixed by hand in `b51912cb8`; the bash one was missed. It has no lexical signature, so the detector could not see it, and no test covered it. That is direct evidence for DBF-REPORT Decision 1, that the class is only partly defended.

A normal Python upgrade does not produce this shape, because the venv name changes with the minor version. Rebuilding a venv in place with another interpreter does, and that is what the owner did by hand during the incident.

A developer agent is fixing it red-first, along with three smaller findings:

- `status` prints no last build when no venv resolves;
- the diagnosis contradicts itself about site-packages;
- the stale `untracked/lsp-venv` pointer, to investigate.

DBF-REPORT gets a "found after merge" entry once the fix lands.
