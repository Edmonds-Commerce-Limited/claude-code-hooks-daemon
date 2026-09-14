# Callout: an upstream issue body now comes from the generator

**Plan**: 00403
**Audience**: client projects

Until now, a project that met daemon misbehaviour had no procedure. Its agent
decided for itself whether the behaviour was a defect, whether the version
mattered, what to include and what to leave out — and then filed into a
repository that is **public**. Three things went wrong there, and they are not
equally bad. A report that turns out to be configuration costs the maintainers
some triage. A report against a version where the bug is already fixed costs
the same. **A report carrying your config, your paths or your logs into a
public issue costs YOU, and no history rewrite reaches it.**

**What changes.** There is now a generator, and a gate that requires it.

```text
hooks-daemon issue-report --fields <file.json>   builds a filable body, or refuses
gh issue create --repo <this repo> --body-file   accepted only for what it built
```

**The redaction guarantee is by construction, not by inspection.** The
generator collects a controlled field set — summary, expectation, observation,
reproduction, the configuration you ruled out, the source line you read. Your
hostname, git remote, environment file, config dump and logs are not scrubbed
out afterwards; they are **never collected**. That is a promise a
scrub-the-output pass cannot make, because a scrubber only removes what it
recognises.

**It refuses before it writes, and returns every reason at once.** A report
that names no source line, cites a line that does not resolve in the installed
version, names a handler this daemon does not have, or does not say which
configuration option was considered and why it was insufficient, is refused —
and on refusal no file exists at all, because a file that exists is a file that
can be filed by mistake. The refusals arrive together, so fixing four problems
takes one round trip rather than four.

**One refusal looks like a defect and is the rule working.** An install BEHIND
the newest release cannot answer the currency question offline: the release
notes that shipped with it stop at its own version, so the notes for the
versions in between are exactly what it does not have. It therefore refuses,
and the remedy is to upgrade.

**The gate: `R-UPSTREAM-ISSUE-UNVERIFIED-BODY`.** `gh issue create` against the
hooks-daemon repository is denied unless `--body-file` names a document the
generator produced and nobody has edited since. Three things it deliberately
leaves alone:

- Issues on **your own** repository. The target is read from `--repo`/`-R`, not
  from this repo's name appearing somewhere in the text, so an issue on your
  backlog titled "upgrade the hooks daemon" is untouched.
- `gh issue comment`, `list` and `view`, against any repository. No generator
  produces a comment body, and requiring provenance on a follow-up would make
  the tracker unusable for the reporter this exists to help.
- The daemon's own repository, where the gate stands down entirely.
- `--web`. It files nothing — it opens GitHub's own issue form, which states
  the same rule and cannot be submitted without ticking two acknowledgements.
  That is the fallback when the generator genuinely cannot run, and it is a
  deliberate hole: a gate whose only escape is evasion teaches evasion.

**Editing a generated report is refused**, because the provenance header
carries a digest of the body. That is the failure this actually catches: a
clean report generated, then edited to paste in "just the relevant bit of the
log", and filed. Extra detail belongs in the reproduction field, where the
checks still run over it.

**What the header is worth, stated precisely:** it is tamper EVIDENCE, not
authentication. Nothing in-process can stop an agent that decides to compute a
digest itself, and no scheme available here would change that. It reliably
catches the accident, which is the failure that actually happens.

**Read the report before you file it.** The gate proves the body is the one the
generator built. It does not prove the prose you wrote inside it is safe to
publish — that judgement is still yours, and it is the one thing no check can
make for you.

**One last check covers the part "collect nothing sensitive" cannot reach.**
The fields you TYPE are scanned against your project's own block-word list
(`.claude/block-words.secret` by default, gitignored), and a match REFUSES the
report. Refused rather than redacted, deliberately: you are still at the
keyboard, the sentence is yours to rewrite, and a silent redaction would teach
you nothing while leaving prose that reads as nonsense. The refusal names
`entry N of M` and never the term, because that message is logged and kept in
context. A project with no list gets silence.

**Where the procedure lives now.** `BUG_REPORTING.md` is the whole thing —
what to establish before filing, the generator, and the filing — and every
other document that used to describe its own version now points at it. The
`hooks-daemon` skill gained an `issue-report` entry that drives it end to end,
and the tracker has issue forms mirroring the generator's fields for anyone
filing from a browser.

**Two instructions that were actively unsafe are gone.** The install and update
guides told you to attach `debug_info.py`'s output "to any bug report", and the
troubleshooting guide asked for your config file "with any sensitive values
removed" — a check that asks you to recognise every one of them by eye, once.
Both of those outputs are local diagnostics for the person who ran them, and
both now say so.
