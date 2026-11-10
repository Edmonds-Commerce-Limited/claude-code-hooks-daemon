# Callout: `/release hotfix` fast path, and advisories no longer fail QA

**Plan**: 00576
**Audience**: everyone

`/release hotfix` (or `/release X.Y.Z hotfix`) cuts an emergency patch release on a shorter path: in-flight plans no
longer stop it at the slate gate (the report still prints), the housekeeping phase, the Claude Code changelog review
and the documentation review are skipped, the code review covers only the hotfix commits, and acceptance testing is the
deterministic gates plus targeted tests for the handlers the fix changed. The release pull request, the full CI gate,
the merge freeze, CI verification, tagging and publishing are unchanged. Separately, an advise-severity `plan_qa` or
`docs_qa` finding is now reported without failing the check; only block-severity findings fail QA and CI.
