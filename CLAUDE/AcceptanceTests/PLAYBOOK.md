# Acceptance Testing Playbook

**Version**: 1.0
**Date**: 2026-01-30
**Purpose**: Validate that all hooks daemon handlers work correctly in real Claude Code usage

---

## ⚠️ CRITICAL SAFETY WARNING ⚠️

**NEVER RUN DESTRUCTIVE COMMANDS DIRECTLY**

This playbook uses **triple-layer safety** for all destructive command tests:

### Layer 1: Use `echo` (MANDATORY)
✅ **CORRECT**: `echo "git reset --hard NONEXISTENT_REF"`
❌ **NEVER DO**: `git reset --hard NONEXISTENT_REF`

### Layer 2: Hooks Block Commands
The daemon hooks will intercept and block destructive commands.

### Layer 3: Fail-Safe Arguments (NEW)
All destructive commands use non-existent refs/paths/files that would fail harmlessly if somehow executed:
- `git reset --hard NONEXISTENT_REF_SAFE_TEST` - non-existent git ref
- `git clean -fd /nonexistent/safe/test/path` - non-existent directory
- `git push --force NONEXISTENT_REMOTE NONEXISTENT_BRANCH` - non-existent remote
- `sed -i 's/foo/bar/' /nonexistent/safe/test.txt` - non-existent file

**Why All Three Layers?**
- Layer 1 (echo): Zero risk even if hooks completely fail
- Layer 2 (hooks): Tests the actual blocking behavior
- Layer 3 (fail-safe args): Defense-in-depth - even catastrophic failure is harmless

**Even with these protections, ALWAYS use echo for destructive commands.**

---

## Prerequisites

Before starting:

1. **Restart daemon to ensure latest code is loaded**:
   ```bash
   $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
   ```
   Should show: `Daemon started successfully`

2. **Verify daemon is running**:
   ```bash
   $PYTHON -m claude_code_hooks_daemon.daemon.cli status
   ```
   Should show: `Status: RUNNING`

3. **Git working tree is clean**:
   ```bash
   git status
   ```
   Should show: `nothing to commit, working tree clean`

---

## Instructions

- Execute each test by attempting the described tool call
- Mark result as PASS or FAIL based on observed behavior
- For blocking handlers: PASS = command blocked with appropriate error
- For advisory handlers: PASS = command allowed with advisory context
- Fill in Results Summary at the end

---

## Test 1: DestructiveGitHandler

**Handler ID**: destructive-git
**Event**: PreToolUse
**Priority**: 10
**Type**: Blocking (terminal=true)

### Test 1.1: git reset --hard

**Command**: `echo "git reset --hard NONEXISTENT_REF_SAFE_TEST"`
**Expected**: BLOCKED with message about destroying uncommitted changes
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent ref - would fail harmlessly if executed

### Test 1.2: git clean -f

**Command**: `echo "git clean -fd /nonexistent/safe/test/path"`
**Expected**: BLOCKED with message about permanently deleting untracked files
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent path - would fail harmlessly if executed

### Test 1.3: git push --force

**Command**: `echo "git push --force NONEXISTENT_REMOTE NONEXISTENT_BRANCH"`
**Expected**: BLOCKED with message about overwriting remote history
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent remote/branch - would fail harmlessly if executed

### Test 1.4: git stash drop

**Command**: `echo "git stash drop stash@{999}"`
**Expected**: BLOCKED with message about permanent deletion
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent stash index - would fail harmlessly if executed

### Test 1.5: git checkout --

**Command**: `echo "git checkout -- /nonexistent/safe/test/file.py"`
**Expected**: BLOCKED with message about discarding changes
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent file path - would fail harmlessly if executed

---

## Test 2: SedBlockerHandler

**Handler ID**: sed-blocker
**Event**: PreToolUse
**Priority**: 11
**Type**: Blocking (terminal=true)

### Test 2.1: sed -i with substitution

**Command**: `echo "sed -i 's/foo/bar/g' /nonexistent/safe/test.txt"`
**Expected**: BLOCKED with message about using Edit tool instead
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent file - would fail harmlessly if executed

### Test 2.2: sed -e command

**Command**: `echo "sed -e 's/old/new/' /nonexistent/safe/test.txt"`
**Expected**: BLOCKED with message about using Edit tool
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent file - would fail harmlessly if executed

---

## Test 3: PipeBlockerHandler

**Handler ID**: pipe-blocker
**Event**: PreToolUse
**Priority**: 12
**Type**: Blocking (terminal=true)

### Test 3.1: npm test piped to tail

**Command**: `echo "npm test | tail -5"`
**Expected**: BLOCKED with message about needing complete output
**Result**: [ ] PASS [ ] FAIL

### Test 3.2: pytest piped to head

**Command**: `echo "pytest | head -20"`
**Expected**: BLOCKED with message about using complete output
**Result**: [ ] PASS [ ] FAIL

---

## Test 4: AbsolutePathHandler

**Handler ID**: absolute-path
**Event**: PreToolUse
**Priority**: 20
**Type**: Blocking (terminal=true)

### Test 4.1: Read with relative path

**Action**: Attempt to Read file `relative/path/file.txt`
**Expected**: BLOCKED with message about requiring absolute path
**Result**: [ ] PASS [ ] FAIL

### Test 4.2: Write with relative path

**Action**: Attempt to Write to `some/relative/path.txt` with content "test"
**Expected**: BLOCKED with message about requiring absolute path
**Result**: [ ] PASS [ ] FAIL

---

## Test 5: TddEnforcementHandler

**Handler ID**: tdd-enforcement
**Event**: PreToolUse
**Priority**: 25
**Type**: Blocking (terminal=true)

### Test 5.1: Create handler without test file

**Action**: Attempt to Write to `/tmp/test-handlers/pre_tool_use/fake_handler.py` with content:
```python
class FakeHandler:
    pass
```
**Expected**: BLOCKED with message about writing tests first (TDD)
**Result**: [ ] PASS [ ] FAIL

---

## Test 6: EslintDisableHandler

**Handler ID**: eslint-disable
**Event**: PreToolUse
**Priority**: 30
**Type**: Blocking (terminal=true)

### Test 6.1: eslint-disable-next-line in JS

**Action**: Attempt to Write to `/tmp/test.js` with content:
```javascript
// eslint-disable-next-line
const x = 1;
```
**Expected**: BLOCKED with message about fixing linting issue instead
**Result**: [ ] PASS [ ] FAIL

### Test 6.2: eslint-disable block in TypeScript

**Action**: Attempt to Write to `/tmp/test.ts` with content:
```typescript
/* eslint-disable */
const y = 2;
/* eslint-enable */
```
**Expected**: BLOCKED with message about fixing linting issue
**Result**: [ ] PASS [ ] FAIL

---

## Test 7: PythonQaSuppressionBlocker

**Handler ID**: python-qa-suppression
**Event**: PreToolUse
**Priority**: 28
**Type**: Blocking (terminal=true)

### Test 7.1: type: ignore comment

**Action**: Attempt to Write to `/tmp/test.py` with content:
```python
x: str = 1  # type: ignore
```
**Expected**: BLOCKED with message about fixing type error instead
**Result**: [ ] PASS [ ] FAIL

### Test 7.2: noqa comment

**Action**: Attempt to Write to `/tmp/test.py` with content:
```python
import os  # noqa
```
**Expected**: BLOCKED with message about fixing the issue instead
**Result**: [ ] PASS [ ] FAIL

---

## Test 8: GoQaSuppressionBlocker

**Handler ID**: go-qa-suppression
**Event**: PreToolUse
**Priority**: 29
**Type**: Blocking (terminal=true)

### Test 8.1: nolint comment

**Action**: Attempt to Write to `/tmp/test.go` with content:
```go
func main() {} // nolint
```
**Expected**: BLOCKED with message about fixing linting issue
**Result**: [ ] PASS [ ] FAIL

---

## Test 9: BritishEnglishHandler

**Handler ID**: british-english
**Event**: PreToolUse
**Priority**: 56
**Type**: Advisory (terminal=false)

### Test 9.1: American spellings in markdown

**Action**: Attempt to Write to `/tmp/docs/test.md` with content:
```markdown
The color of the organization is gray.
```
**Expected**: ALLOWED with advisory suggesting "colour", "organisation", "grey"
**Result**: [ ] PASS [ ] FAIL

**Notes**:

---

## Test 10: WebSearchYearHandler

**Handler ID**: web-search-year
**Event**: PreToolUse
**Priority**: 50
**Type**: Advisory (terminal=false)

### Test 10.1: Outdated year in search query

**Action**: Observational - attempt web search with "Python documentation 2024" in query
**Expected**: ALLOWED with advisory suggesting current year (2026)
**Result**: [ ] PASS [ ] FAIL [ ] SKIP (if WebSearch not available)

**Notes**:

---

## Test 11: BashErrorDetectorHandler

**Handler ID**: bash-error-detector
**Event**: PostToolUse
**Priority**: N/A
**Type**: Advisory (terminal=false)

### Test 11.1: Failed command detection

**Command**: `ls /nonexistent/path/that/does/not/exist`
**Expected**: Command fails, then advisory context mentions detected error
**Result**: [ ] PASS [ ] FAIL

**Notes**:

---

## Test 12: PlanWorkflowHandler

**Handler ID**: plan-workflow
**Event**: PreToolUse
**Priority**: 48
**Type**: Advisory (terminal=false)

### Test 12.1: Writing to PLAN.md file

**Action**: Attempt to Write to `/tmp/CLAUDE/Plan/00999-test/PLAN.md` with content:
```markdown
# Test Plan
```
**Expected**: ALLOWED with advisory about plan workflow
**Result**: [ ] PASS [ ] FAIL

**Notes**:

---

## Test 13: GitContextInjectorHandler

**Handler ID**: git-context
**Event**: UserPromptSubmit
**Priority**: N/A
**Type**: Context Injection (terminal=false)

### Test 13.1: Git context in responses

**Action**: Observational - check if git branch/status appears in hook context
**Expected**: Git context visible in UserPromptSubmit hook responses
**Result**: [ ] PASS [ ] FAIL

**Notes**:

---

## Test 14: WorkflowStateRestorationHandler

**Handler ID**: workflow-state
**Event**: SessionStart
**Priority**: N/A
**Type**: Context Injection (terminal=false)

### Test 14.1: Session start after compaction

**Action**: Requires session compaction event (not testable on demand)
**Expected**: Workflow state restored after compaction
**Result**: [ ] SKIP (requires compaction)

**Notes**: Cannot trigger SessionStart events on demand

---

## Test 15: DaemonStatsHandler

**Handler ID**: daemon-stats
**Event**: StatusLine
**Priority**: 30
**Type**: Context Injection (terminal=false)

### Test 15.1: Daemon stats in status line

**Action**: Observational - check if status line shows daemon stats
**Expected**: Status line displays daemon uptime/memory/handler count
**Result**: [ ] PASS [ ] FAIL [ ] SKIP (if status line not configured)

**Notes**:

---

## Cleanup

After completing all tests, clean up temporary files:

```bash
rm -rf /tmp/test.js /tmp/test.ts /tmp/test.py /tmp/test.go
rm -rf /tmp/test-handlers
rm -rf /tmp/docs
rm -rf /tmp/CLAUDE
```

---

## Results Summary

| # | Handler | Type | Result | Notes |
|---|---------|------|--------|-------|
| 1 | DestructiveGitHandler | Blocking | [ ] PASS [ ] FAIL | |
| 2 | SedBlockerHandler | Blocking | [ ] PASS [ ] FAIL | |
| 3 | PipeBlockerHandler | Blocking | [ ] PASS [ ] FAIL | |
| 4 | AbsolutePathHandler | Blocking | [ ] PASS [ ] FAIL | |
| 5 | TddEnforcementHandler | Blocking | [ ] PASS [ ] FAIL | |
| 6 | EslintDisableHandler | Blocking | [ ] PASS [ ] FAIL | |
| 7 | PythonQaSuppressionBlocker | Blocking | [ ] PASS [ ] FAIL | |
| 8 | GoQaSuppressionBlocker | Blocking | [ ] PASS [ ] FAIL | |
| 9 | BritishEnglishHandler | Advisory | [ ] PASS [ ] FAIL | |
| 10 | WebSearchYearHandler | Advisory | [ ] PASS [ ] FAIL [ ] SKIP | |
| 11 | BashErrorDetectorHandler | Advisory | [ ] PASS [ ] FAIL | |
| 12 | PlanWorkflowHandler | Advisory | [ ] PASS [ ] FAIL | |
| 13 | GitContextInjectorHandler | Context | [ ] PASS [ ] FAIL | |
| 14 | WorkflowStateRestorationHandler | Context | [ ] SKIP | |
| 15 | DaemonStatsHandler | StatusLine | [ ] PASS [ ] FAIL [ ] SKIP | |

**Total**: ___ PASS, ___ FAIL, ___ SKIP

**Test Date**: ___________
**Daemon Version**: ___________
**Tester**: ___________

---

## Test Execution Notes

### Issues Found


### Handlers Working Correctly


### Recommendations


---

**End of Playbook**
