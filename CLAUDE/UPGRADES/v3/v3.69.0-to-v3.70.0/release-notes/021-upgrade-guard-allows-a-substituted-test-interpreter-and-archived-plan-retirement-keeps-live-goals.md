# Callout: a substituted test interpreter no longer trips the upgrade guard, and retiring an archived plan keeps the live goals

**Plan**: 00474
**Audience**: everyone

The upgrade-approval guard (`R-UPGRADE-APPROVAL-ENV-BYPASS`) denied a plain test run whose interpreter was a command substitution, such as `PYTHONPATH=<src> $(ls -d venv-*/bin/python) -m pytest tests/...`. It split the substitution at its spaces, took the tail for a script it could not read, and counted that as the upgrade because `PYTHONPATH` steers. The program word is now read whole. A substituted interpreter given `-m <module>` (attached, as in `-mpytest`, or separate) is judged by the module, as a `$PY` variable already was, and the command inside the substitution is checked for the upgrade as well. Real bypasses stay denied: an upgrade script run through a shell, a substituted program that is itself the upgrade, a computed script, module or `-c` program, and the daemon's own `-m claude_code_hooks_daemon...`.

When a plan's PLAN.md sits under `Completed/`, the goal handler now reads the live plans from the plan root, not from `Completed/`. Previously a retirement refresh given an archived path found no live plan and cleared every owner's `/goal`. Writes under `Completed/` are not matched by the handler, so this closes a latent path rather than a reproduced one.

`TeammateIdle`, `TaskCreated` and `TaskCompleted` are now events on which a handler `scope` of `MAIN` or `SUB` is accepted, as their contracts declare `agent_id`. No handler changes behaviour: the default scope is still `ALL`.
