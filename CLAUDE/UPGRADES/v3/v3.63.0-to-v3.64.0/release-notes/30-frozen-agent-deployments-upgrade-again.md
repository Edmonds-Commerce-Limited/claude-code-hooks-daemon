# Callout: agent deployments wrongly frozen as "customised" upgrade again

**Plan**: 00378
**Audience**: operators

If the daemon ever told you that a file under `.claude/agents/` "does not match
any revision the daemon ever shipped — it has been CUSTOMISED locally", and you
had not edited it, the daemon was wrong. Those deployments start upgrading
again after this release, with nothing for you to do.

**What happened.** A deployed agent is refreshed when its content matches the
current shipped revision or a recorded historic one; anything else is treated as
your own work and never touched. That protection is correct, but it depends on
every shipped revision being recorded — and four were not, across all three
shipped agents. A project that installed during one of those windows held a
pristine file the daemon could not recognise, so it was classified as customised
and refused for ever, with a message blaming the reader for an edit they never
made.

The four revisions are now recorded, so those files classify as merely outdated
and the next upgrade refreshes them normally.

**Why they went unrecorded.** The check meant to catch exactly this compared the
bundled file's digest against a value computed from that same file — it compared
a value with itself, so it could not fail, while its description claimed that
editing a bundled agent without recording its digest "must fail loudly here,
never ship silently". The digest is now declared as data and compared against
the file, and a second check walks each template's full git history and fails if
any revision it has ever had is missing from the ledger. Both were watched
failing on a deliberately broken input before being accepted.

**Nothing about the protection itself has changed.** A genuinely customised
agent is still never overwritten by an upgrade or a bulk refresh. If you want to
discard local edits and return to the shipped revision, that remains an explicit,
per-agent choice:

```bash
hooks-daemon agents install <agent-name> --force
```

**If you previously worked around this** by deleting an agent file to force a
clean redeploy, nothing needs undoing — the file you have now is the shipped
revision either way.
