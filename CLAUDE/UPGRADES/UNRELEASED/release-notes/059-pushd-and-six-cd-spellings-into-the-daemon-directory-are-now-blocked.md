# Callout: `pushd` and six more `cd` spellings into the daemon directory are now blocked

**Plan**: 00408
**Audience**: client projects

`R-DAEMON-DIR-CD` now matches `pushd .claude/hooks-daemon` and `cd` with
options before the path (`cd -- <path>`, `cd -P <path>`). It also matches
quoting or an escape inside the path (`.claude/'hooks-daemon'`,
`.cl\aude/hooks-daemon`) and a doubled `//`. Every one of these changed into
the directory and was allowed. `popd` and `cd -` are still not matched,
because they name no path.
