# Callout: plan QA can now list its checks

**Plan**: 00466
**Audience**: client projects

`hooks-daemon plan-qa --list-checks` prints every plan QA check and the stages
it runs on (edit, commit, sweep), with each stage's level. It reads the check
registry, so it is always current. The plan workflow guide said the plan index
was "linted against one rule", which had not been true for some time. It now
names checks only as examples and points at this listing.
