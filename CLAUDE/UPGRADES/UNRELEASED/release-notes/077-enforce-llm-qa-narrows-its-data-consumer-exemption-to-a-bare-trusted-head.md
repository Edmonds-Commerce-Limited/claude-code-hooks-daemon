# Callout: `enforce_llm_qa` narrows its data-consumer exemption to a bare, trusted head

**Plan**: 00466
**Audience**: handler authors

The `cat`/`grep`/`git`/etc. data-consumer exemption matched on a command's
BASENAME, so a path-qualified head (`/usr/bin/cat`) got the same free pass
as the bare trusted word, and it did not exclude `git`/`rg` shapes that
themselves execute an argument (`git bisect run <cmd>`, `git rebase -x <cmd>`, `git -c alias.NAME=!<cmd>`, `rg --pre <cmd>`). The exemption now
requires the head to be spelled exactly as the bare trusted word (no path
prefix at all), and is voided outright for those four executing shapes, so
each falls through to the ordinary invocation check instead of an early
allow.
