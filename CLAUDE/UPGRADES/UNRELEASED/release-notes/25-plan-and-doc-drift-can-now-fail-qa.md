# Callout: plan-tree and doc-corpus drift can now fail QA, and a merge no longer lands it unremarked

**Plan**: 00373
**Audience**: everyone

`plan-qa --sweep` and `docs-qa --sweep` have always exited non-zero on
findings, but neither was a QA tool — so drift in either corpus could not
fail QA, CI, or the release gate, and did not: a merge resurrected an
archived plan folder and the four plan-QA findings about it survived a fully
green QA run, a green CI run and a release-slate check. Both sweeps are now
registered QA tools, and **any** finding fails, at either severity. That is
a deliberate departure from how the same advise/block split behaves at the
commit gate, where it decides who gets blamed for a commit; QA asks a
different question — is the tree clean now. Each check keeps its own
configured allowlist, so a finding left standing is a decision rather than
an accident.

The reason that drift arrived unseen is now fixed too. Every commit-time
gate — `plan_qa_commit_gate`, `docs_qa_commit_gate`, `staged_lint_gate` —
keys on a `git commit` command, and a `git merge`, `git pull` or `git rebase` creates a commit without ever invoking one. A new advisory,
`merge_qa_report`, runs after such an operation and reports the plan-QA and
docs-QA findings attributable to what it actually introduced, using
`ORIG_HEAD..HEAD`. It is silent when nothing moved and when nothing is
attributable, so pre-existing drift is not re-surfaced on every merge. The
merge has already landed by then, so it is a report to repair from — in the
same idiom as `lint_on_edit` — never a reason to try to undo the merge.
