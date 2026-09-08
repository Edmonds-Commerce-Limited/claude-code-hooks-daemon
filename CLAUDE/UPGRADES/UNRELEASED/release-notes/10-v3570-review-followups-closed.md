# Callout: the v3.57.0 review ledger is worked to zero

**Plan**: 00295
**Audience**: operators

Every non-blocking finding from the v3.57.0 release review is now fixed. The
ones an operator can see: lint and ESLint skip paths match on path segments,
so `src/rebuild/x.py` is no longer skipped as if it were `build/`; a
symlinked file no longer turns a docs QA check into a stack-trace deny;
`layout.source_dirs` and `layout.test_dirs` match paths and globs as their
descriptions always said; a timed-out transport probe kills what it started
instead of orphaning a forwarder; `explain-handler --list` exists, so the
advisory handlers that carry no rule ID can be found; `transport-probe`
reports the relay digest it verified instead of `unknown (no manifest)`; and
the `nc` relay rung honours `HOOKS_DAEMON_EVENTS_DIR` on deep client layouts.
The acceptance playbook now probes for `llm:lint` before emitting the ESLint
tests, so a repository without `package.json` no longer sees them as runnable.
