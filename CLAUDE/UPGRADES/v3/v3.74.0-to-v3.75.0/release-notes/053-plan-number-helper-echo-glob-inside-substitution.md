# Callout: plan_number_helper no longer denies a content search inside an echo's substitution

**Plan**: 00597
**Audience**: client projects

`plan_number_helper` (R-PLAN-NUMBER-DISCOVERY) denied `echo "found: $(grep -rl takeover CLAUDE/Plan/00001*/subagent-reports/)"`, a content search of ONE plan, because its echo/printf glob rule read the `*` of the grep's path as an echoed plan-folder glob. Two changes:

- **A substitution is opaque to the echo/printf rule.** The rule steps over `$(...)`, backticks and `<(...)` instead of reading into them. A glob inside belongs to the inner command, which is judged by its own rules, so `$(ls -d CLAUDE/Plan/* | tail -1)` still denies while `$(grep -rl x CLAUDE/Plan/00001*/)` does not.
- **A glob opening with a full plan number names one plan.** `echo CLAUDE/Plan/00001*/PLAN.md` and `echo CLAUDE/Plan/00001-*` are lookups, as they already were for `ls`. `echo CLAUDE/Plan/*`, `echo CLAUDE/Plan/0*` and `printf '%s\n' CLAUDE/Plan/*/` still deny.
