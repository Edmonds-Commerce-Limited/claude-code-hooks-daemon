# Callout: optional seed entries are not reported as MISSING

**Plan**: 00580
**Audience**: client projects

`hooks-daemon check-worktree-seed` listed a configured seed entry under MISSING whenever its source was absent, even
when the entry was marked `optional: true`. Creation-time seeding already skips an absent optional source, so the report
claimed that the next worktree creation would abort and told the reader to remove an entry that was working as
designed. The report now lists only absent required entries under MISSING. An absent optional entry is no longer
reported, a present one is unchanged, and creation-time seeding is unchanged. GitHub #167.
