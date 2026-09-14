# Callout: a running daemon notices its own upgrade

**Plan**: 00395
**Audience**: client projects

The daemon loads its code once, at startup, and serves it for the life of the
process. It never hot-reloads. So when a **different session or process on the
same filesystem** upgrades this project's installed daemon, the one already
running keeps serving everything it loaded — every safety handler in it is the
old version — and nothing said so.

This is not the same gap as "my daemon is out of date". The daemon already
checked that, at the moments it could: `check-source-fresh` during a QA sweep,
`daemon_restart_verifier` on an in-session source edit, and
`daemon_sync_after_merge` when a pull moved the version marker. All three key
on something happening *in this session*. An upgrade run from a second terminal
is invisible to all of them, and the only symptom is behaviour that quietly
does not match what is installed.

**What changes.** A new `daemon_upgrade_detector` handler runs on every
UserPromptSubmit and compares two things:

```text
in-memory   claude_code_hooks_daemon.version.__version__    what THIS process loaded
on-disk     <venv>/.daemon-metadata.json -> daemon_version  what is installed NOW
```

When they differ it names both versions and the restart command. When they
match it produces **nothing at all** — an advisory on every user turn for a
fact that changes at most once per upgrade would be worse than the defect it
reports.

**It re-resolves the venv rather than remembering it, and that is the whole
subtlety.** The venv directory is fingerprint-keyed
(`untracked/venv-{slug}-py{MM}-{fingerprint}/`), so an upgrade that changes the
fingerprint inputs writes a **new venv directory** instead of rewriting the old
one. A check that re-read the path it resolved at startup — or trusted
`sys.prefix`, which still points at the old venv inside the running process —
would find an untouched file and report "fresh" forever, in exactly the case it
exists to catch. The resolution is redone on every check.

**It advises and never acts.** It does not restart, and it does not upgrade.
That is the standing rule Plans 00386 and 00389 already ship under, and here it
is also a hard constraint: this handler runs *inside* the daemon serving the
very hook that triggered it, so a self-restart would drop the response the
session is waiting on.

**Dormant in a self-install checkout.** Where the daemon runs from `src/` in
the repository itself there is no separately deployed clone for another session
to replace, so the handler reports `is_dormant()` and is left out of the
generated `CLAUDE.md` entirely rather than announced as policy that cannot
apply. Client projects with an installed `.claude/hooks-daemon/` clone are the
whole audience.

**Fail-open, unconditionally.** A missing, unreadable, malformed or
unparseable metadata file means "cannot tell", and every one of those allows
the hook through. A version check is not worth a blocked session.
