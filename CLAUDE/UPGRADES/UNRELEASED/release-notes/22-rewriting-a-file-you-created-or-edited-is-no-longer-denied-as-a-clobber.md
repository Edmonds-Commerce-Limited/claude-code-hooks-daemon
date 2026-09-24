# Callout: rewriting a file you created or edited is no longer denied as a clobber

**Plan**: 00422
**Audience**: everyone

`write_clobber_guard` recorded only `Read` calls. So a session that created a
file with `Write` got `R-WRITE-CLOBBER` when it wrote that file again, even
though the deny text says a file you wrote earlier in the session is not
blocked. That text now holds: a `Write` that creates or rewrites a file you
already know about, and any `Edit`, marks the file as known for your session.
Two spellings of the same path (`/a/b/../c` and `/a/c`) now count as one file.
Nothing changes for other sessions: a file another session wrote is still
unknown to yours, and a `Write` over it is still denied until you `Read` it. A
new QA check, `unreachable_handle_branch`, catches the cause. The guard did its
recording in a branch of `handle()` that the dispatcher never reaches.
