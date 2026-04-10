# Bug Report: `sed_blocker` Handler Bypassed via `xargs sed`

**Severity**: MEDIUM — Safety handler can be circumvented by piping through xargs.

**Daemon Version**: 2.10.0 (installed)
**Affected Handler**: `sed_blocker` (PreToolUse)

## Summary

The `sed_blocker` handler blocks direct `sed -i` commands but does not detect `sed` when invoked indirectly via `xargs`, `find -exec`, or other command wrappers. This allows the exact pattern the handler is designed to prevent.

## Reproduction

### Blocked (correctly):

```bash
sed -i 's|CLAUDE/Plans|CLAUDE/Plan|g' CLAUDE.md
# → Blocked by sed_blocker handler
```

### Not blocked (bypass):

```bash
grep -rl 'CLAUDE/Plans' | xargs sed -i 's|CLAUDE/Plans|CLAUDE/Plan|g'
# → Executes successfully, handler does not fire
```

## Root Cause

The handler likely matches `sed` at the start of the command string or as the primary command, but does not scan for `sed` appearing after pipe operators or as an argument to `xargs`, `find -exec`, `parallel`, etc.

## Bypass Patterns That Should Be Caught

```bash
# xargs variants
grep -rl 'pattern' | xargs sed -i 's/old/new/g'
find . -name '*.md' | xargs sed -i 's/old/new/g'
xargs sed -i 's/old/new/g' < filelist.txt

# find -exec variants
find . -name '*.md' -exec sed -i 's/old/new/g' {} \;
find . -name '*.md' -exec sed -i 's/old/new/g' {} +

# Other wrappers
parallel sed -i 's/old/new/g' ::: file1 file2
env sed -i 's/old/new/g' file.txt
command sed -i 's/old/new/g' file.txt
```

## Proposed Fix

The handler's `matches()` method should scan the entire command string for `sed -i` (or `sed` with in-place flags), not just check if the command starts with `sed`. A regex like:

```python
# Match sed -i anywhere in the command, including after pipes and xargs
re.search(r'\bsed\s+.*-i', command)
```

This would catch `sed -i` regardless of whether it appears at the start, after a pipe, or as an argument to `xargs`/`find -exec`.

## Observed Instance

On 2026-03-09, the following command executed successfully without being blocked:

```bash
grep -rl 'CLAUDE/Plans' --include='*.md' --include='*.yaml' --include='*.yml' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.json' | xargs sed -i 's|CLAUDE/Plans|CLAUDE/Plan|g'
```

This modified 38 files in a single unreviewed sed operation — exactly the kind of bulk in-place edit the handler exists to prevent.
