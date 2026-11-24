# Callout: mkplan --journal takes a folder name, and find-plan can search plan text

**Plan**: 00636
**Audience**: operators

`mkplan.bash --journal` now accepts a plan's full folder name (`00042-my-plan`, a trailing slash tolerated) as well as its number; the folder must exist exactly, so a wrong slug is refused and writes nothing. The one-line synopsis in `--help` and in the `--journal` usage now lists the legal categories and states the `--ref` format a correction needs (`HH:MM` for today, `YY-MM-DD/HH:MM` for an earlier day). Every earlier invocation (plan creation, `--journal` with a bare number, `--resolve-conflict`) behaves as before. `bin/hooks-daemon find-plan --body <text>` also matches the text of each PLAN.md, `Completed/` included; without `--body` it still matches only number, folder name and title. The deployed `CLAUDE/Plan/mkplan.bash` is refreshed by the normal upgrade.
