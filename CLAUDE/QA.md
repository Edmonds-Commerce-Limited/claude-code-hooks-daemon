# Quality Assurance Pipeline

**Version**: 1.0
**Status**: Primary source of truth for QA workflow
**Audience**: All developers and AI agents

---

## Overview

Complete quality assurance for the Claude Code Hooks Daemon consists of **three layers**:

1. **Automated QA** (`./scripts/qa/run_all.sh`) - Fast, deterministic checks
2. **Sub-Agent QA** (via Task tool) - Deep architectural review and value verification
3. **Acceptance Testing** (Agentic) - Real-world scenario validation performed by AI agents before release

**CRITICAL**: All three layers are required for production-ready code. Each layer catches different types of issues.

---

## Automated QA (Layer 1)

### Running Automated QA

```bash
./scripts/qa/run_all.sh
```

### The 7 Automated Checks

1. **Magic Values Check** (`check_magic_values.py`)
   - Detects hardcoded strings/numbers that should be constants
   - Enforces single source of truth for all values
   - Rules: handler names, priorities, tool names, event types, tags

2. **Format Check** (Black)
   - Code formatting (line length 100)
   - Auto-fixes with `./scripts/qa/run_autofix.sh`

3. **Linter** (Ruff)
   - Style violations, code smells, common bugs
   - Auto-fixes with `./scripts/qa/run_autofix.sh`

4. **Type Check** (MyPy)
   - Strict mode type checking
   - All functions must have type annotations

5. **Tests** (Pytest)
   - Minimum 95% code coverage required
   - Unit tests + integration tests

6. **Security Check** (Bandit)
   - Scans for security vulnerabilities
   - Zero HIGH/MEDIUM/LOW issues allowed

7. **Dependency Check** (Deptry)
   - Missing dependencies (DEP001)
   - Misplaced dependencies (DEP004)

### Success Criteria

All 7 checks must pass with ZERO failures:

```
========================================
QA Summary
========================================
  Magic Values        : ✅ PASSED
  Format Check        : ✅ PASSED
  Linter              : ✅ PASSED
  Type Check          : ✅ PASSED
  Tests               : ✅ PASSED
  Security Check      : ✅ PASSED
  Dependencies        : ✅ PASSED

Overall Status: ✅ ALL CHECKS PASSED
```

**If ANY check fails**: Fix issues and re-run. Do not proceed until all pass.

---

## Sub-Agent QA (Layer 2)

### When to Run Sub-Agent QA

Sub-agent QA is required for:
- ✅ Architectural changes (new handlers, refactoring)
- ✅ Complex features (multiple files, cross-cutting concerns)
- ✅ Before merging significant work
- ✅ When using agent teams (see `CLAUDE/AgentTeam.md`)

Sub-agent QA is optional for:
- Small bug fixes (single file, trivial change)
- Documentation-only changes
- Configuration updates

### QA Agent Role (Gate 2)

**Primary Responsibility**: Verify code meets quality standards beyond automated checks.

**Spawning QA Agent**:

```python
Task(
    subagent_type="general-purpose",
    name="qa-agent",
    prompt="""You are a QA AGENT verifying code quality.

YOUR ROLE (QA - Gate 2):
Verify code meets quality standards (format, lint, types, coverage, security).

WORKFLOW:
1. cd to target directory
2. Run: ./scripts/qa/run_all.sh (all 7 checks)
3. Verify daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status
4. Check coverage: MUST be 95%+ (shown in QA output)
5. Verify no security issues (Bandit must pass)
6. **Check library/plugin separation** (see checklist below)
7. Report "QA verified" OR "QA failed with details"

PASS CRITERIA:
- All 7 QA checks pass (magic values, format, lint, types, tests, security, dependencies)
- Coverage ≥ 95%
- Daemon restarts successfully
- No security issues
- Library/plugin separation maintained (no project-specific handlers in library)

LIBRARY/PLUGIN SEPARATION CHECKLIST:
8. Library/Plugin Separation:
   - Scan src/claude_code_hooks_daemon/handlers/
   - Flag handlers that reference @CLAUDE/ paths
   - Flag "dogfooding" language (project-specific)
   - Flag project-specific functionality
   - Report violations found

LIBRARY HANDLERS (Generic, Reusable):
✅ Generic safety enforcement (destructive git, sed blocker)
✅ Generic QA enforcement (ESLint disable, TDD enforcement)
✅ Generic workflow patterns (plan numbering, npm commands)
✅ Tool usage guidance (web search year)
✅ Reusable by any project
✅ NO project-specific references

Examples: destructive_git, tdd_enforcement, sed_blocker, eslint_disable

PROJECT PLUGINS (Project-Specific):
⚠️ Project-specific functionality
⚠️ Dogfooding language/concepts
⚠️ References @CLAUDE/ documentation
⚠️ Specific to developing this project
⚠️ NOT reusable by other projects

Examples: dogfooding_reminder (references @CLAUDE/CodeLifecycle/Bugs.md)

VIOLATION DETECTION:
- grep -r "@CLAUDE" src/claude_code_hooks_daemon/handlers/
- grep -r "dogfooding" src/claude_code_hooks_daemon/handlers/
- Read handler code - does it reference project-specific docs/concepts?

REPORT FORMAT (PASS):
SendMessage(type="message", recipient="team-lead",
  content="QA complete. All 7 checks pass. Coverage: XX%. Daemon restarts. Library/plugin separation verified: no violations. Ready for review.",
  summary="QA verified - pass")

REPORT FORMAT (FAIL):
SendMessage(type="message", recipient="team-lead",
  content="QA FAILED. Issues: [specific failures]. Library/plugin violations: [list violations]. Sending back to developer.",
  summary="QA failed - rejected")
"""
)
```

### Senior Reviewer Role (Gate 3)

**Primary Responsibility**: Verify work is COMPLETE per plan and architecturally sound.

**Spawning Senior Reviewer**:

```python
Task(
    subagent_type="general-purpose",
    name="senior-reviewer",
    prompt="""You are a SENIOR REVIEWER AGENT reviewing completeness and architecture.

YOUR ROLE (Senior Reviewer - Gate 3):
Verify work is COMPLETE per plan and architecturally sound.

WORKFLOW:
1. cd to target directory
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md (goals, success criteria, phases)
3. Review all code: git log [branch] --stat
4. Verify ALL plan phases complete (not partial)
5. Check architecture (no duplication, correct patterns)
6. Verify success criteria met
7. Report "approved" OR "rejected with specific gaps"

CRITICAL CHECKS:
- If plan has N phases, ALL N must be complete
- If plan says "eliminate DRY", verify no duplication remains
- If plan says "42 tests", count that 42 exist
- If plan says "integrated with config", verify in config file
- Reject "ready for phase 2" (means incomplete)

REPORT FORMAT (APPROVED):
SendMessage(type="message", recipient="team-lead",
  content="Review complete. ALL phases done. Success criteria met: [list]. Architecture sound. Ready for honesty check.",
  summary="Review approved")

REPORT FORMAT (REJECTED):
SendMessage(type="message", recipient="team-lead",
  content="Review REJECTED. Incomplete: [gaps]. Phases X,Y,Z not done. Back to developer.",
  summary="Review rejected - incomplete")
"""
)
```

### Honesty Checker Role (Gate 4 - FINAL)

**Primary Responsibility**: Verify work delivers REAL VALUE, not just "looks complete". Detect theater, lazy solutions, and false claims.

**Spawning Honesty Checker**:

```python
Task(
    subagent_type="general-purpose",
    name="honesty-checker",
    prompt="""You are an HONESTY CHECKER AGENT auditing for theater and value delivery.

YOUR ROLE (Honesty Checker - Gate 4 - FINAL):
Verify work delivers REAL VALUE, not just "looks complete".
Detect theater, lazy solutions, shitty implementations, and false claims.

CRITICAL UNDERSTANDING:
- Code can pass tests and still be theater if it doesn't deliver real value
- Tests can exist but not prove anything meaningful (TDD theater)
- Handlers can "work" but be lazy/shitty implementations
- Features can be "done" but not really solve the problem

YOUR JOB: Ask "Does this ACTUALLY deliver the value implied by the feature?"

WORKFLOW:
1. cd to target directory
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md (understand what VALUE should be delivered)
3. Perform DEEP VALUE AUDIT (not just code existence check)
4. READ ACTUAL CODE - don't just check files exist
5. READ ACTUAL TESTS - do they prove behavior or just exist?
6. Ask: "Would I accept this in code review or reject as lazy/incomplete?"
7. Report "genuine completion" OR "theater detected - REJECT"

THEATER DETECTION CHECKS:

Check 1 - Dead Code Theater:
  git grep "from.*[module_name] import"
  If module created but never imported → THEATER
  VALUE CHECK: Is code actually USED in application flow?

Check 2 - Config Theater:
  cat .claude/hooks-daemon.yaml
  If handler missing from config → THEATER
  VALUE CHECK: Is handler ACTIVE and intercepting events?

Check 3 - TDD Theater (Tests That Don't Prove Anything):
  grep -c "def test_" tests/path/to/test_file.py
  Compare to claimed count
  READ THE ACTUAL TESTS - do they test real behavior or just existence?

  Example TDD theater:
    def test_handler_exists():
        assert HandlerName() is not None  # Proves NOTHING

  VALUE CHECK: Do tests actually PROVE the feature works?

Check 4 - Handler Theater (Handlers That Don't Really Work):
  READ the actual handler code (don't just check it exists)
  VALUE CHECK: Does handler actually BLOCK/ALLOW/ADVISE correctly?

Check 5 - Lazy Solution Theater (Works But Is Shitty):
  VALUE CHECK: Is this a PROPER solution or lazy workaround?
  Ask: Would I accept this in code review or reject as lazy?

Check 6 - Goal Achievement Theater:
  Read plan goals: "eliminate DRY violations in handlers X,Y,Z"
  ACTUALLY CHECK handlers X,Y,Z for remaining duplication
  VALUE CHECK: Did they SOLVE the problem or just write code?

Check 7 - Phase Completion Theater:
  If plan has 8 phases, verify artifacts for ALL 8
  VALUE CHECK: Are phases actually DONE or just "started"?

Check 8 - Integration Theater:
  VALUE CHECK: Do all pieces WORK TOGETHER?

YOU CAN (and SHOULD):
- VETO entire branch if theater detected
- Reject even if tests pass (if tests are theater)
- Reject handlers that "work" but are lazy/shitty
- Call out solutions that technically work but aren't proper

REPORT FORMAT (GENUINE):
SendMessage(type="message", recipient="team-lead",
  content="Honesty check PASSED.

  VALUE VERIFICATION:
  - Code delivers real value (not just exists)
  - Tests PROVE feature works (not TDD theater)
  - Handler is PROPER implementation (not lazy)
  - Solution maintainable, follows patterns
  - Plan goals ACTUALLY achieved

  TECHNICAL VERIFICATION:
  - Code used in application flow
  - Handler in config and active
  - X tests exist, test real behavior
  - ALL phases complete
  - No theater detected

  APPROVED FOR MERGE.",
  summary="Genuine - approved")

REPORT FORMAT (THEATER):
SendMessage(type="message", recipient="team-lead",
  content="THEATER DETECTED.

  EVIDENCE:
  [Specific findings with code examples]
  - TDD theater: Tests don't prove behavior
  - Handler theater: Doesn't really solve problem
  - Lazy solution: Works but shitty/incomplete
  - Unachieved goals: Plan says X, code doesn't deliver

  VALUE ASSESSMENT:
  This does NOT deliver the value implied by feature.
  [Explain what's missing/wrong]

  ENTIRE BRANCH REJECTED. [Recommend: fix issues / redesign]",
  summary="Theater - REJECTED")
"""
)
```

---

## Acceptance Testing (Layer 3)

**Purpose**: Validate handlers work correctly in real-world scenarios before release.

**When Required**: Before production releases, after significant changes, for new handlers.

### Acceptance Testing Overview

**See `CLAUDE/AcceptanceTests/GENERATING.md` for complete acceptance testing guide.**

Acceptance testing is **agentic** - AI agents execute real-world test scenarios:
- Test definitions are in handler code (`get_acceptance_tests()` method)
- Playbooks are generated fresh from code (ephemeral, never committed)
- **AI agents execute the playbook** and validate behavior
- Tests cover real-world usage scenarios
- Triple-layer safety (echo commands, hook blocking, fail-safe arguments)

### Running Acceptance Tests

```bash
# 1. Generate fresh playbook (ephemeral)
$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md

# 2. Execute tests manually following playbook
# ... test each scenario ...

# 3. Delete ephemeral playbook when done
rm /tmp/playbook.md
```

### FAIL-FAST Cycle (CRITICAL)

**ANY bug found during acceptance testing = Complete the full cycle:**

```
Acceptance Testing → Find Bug → STOP → Fix with TDD → Run Full QA → Restart Daemon → RESTART FROM TEST 1.1
```

**Why restart from Test 1.1?**
Your fix might have affected earlier tests. Full re-run ensures no regressions.

**Process**:
1. Generate fresh playbook
2. Execute tests sequentially
3. **If bug found**: STOP immediately
4. Fix bug using TDD (write failing test, implement fix, verify)
5. Run FULL QA: `./scripts/qa/run_all.sh` (must pass 100%)
6. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
7. **Regenerate playbook** (to reflect fix)
8. **RESTART from Test 1.1** (not from where you left off)
9. Continue until ALL tests pass with ZERO code changes

### Success Criteria

✅ All acceptance tests pass
✅ No code changes during testing run
✅ All handlers behave as expected in real scenarios
✅ Blocking handlers prevent dangerous operations
✅ Advisory handlers provide helpful context

### Acceptance Test Example

```python
def get_acceptance_tests(self) -> list[AcceptanceTest]:
    """Acceptance tests for destructive git handler."""
    return [
        AcceptanceTest(
            title="git reset --hard",
            command='echo "git reset --hard NONEXISTENT_REF"',
            description="Blocks destructive git reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[
                r"destroys.*uncommitted changes",
                r"permanently"
            ],
            safety_notes="Uses non-existent ref - harmless if executed",
            test_type=TestType.BLOCKING
        )
    ]
```

### Plugin Handlers

**Custom plugins are automatically included** in generated playbooks.

All plugin handlers MUST implement `get_acceptance_tests()` - empty arrays are rejected.

**See `CLAUDE/AcceptanceTests/GENERATING.md` for complete documentation.**

---

## Complete QA Workflow

### For Individual Work (No Agent Teams)

1. **During development**: Write tests first (TDD)
2. **Before committing**: Run `./scripts/qa/run_all.sh` (automated QA)
3. **Fix any issues**: Use `./scripts/qa/run_autofix.sh` for format/lint
4. **Verify daemon**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
5. **For significant work**: Spawn QA Agent for deep review

### For Agent Team Work

Follow the 4-gate verification process:

```
Developer Agent
    ↓ Reports "ready for testing"
    ↓
Tester Agent (GATE 1) - Tests verified
    ↓
QA Agent (GATE 2) - Quality verified (including library/plugin separation)
    ↓
Senior Reviewer (GATE 3) - Completeness verified
    ↓
Honesty Checker (GATE 4) - Value verified
    ↓
Merge (ONLY after all 4 gates pass)
```

**See `CLAUDE/AgentTeam.md` for complete agent team workflow details.**

---

## Library vs Plugin Separation (CRITICAL)

### Library Handlers (src/claude_code_hooks_daemon/handlers/)

**Criteria**:
✅ Generic safety enforcement
✅ Generic QA enforcement
✅ Generic workflow patterns
✅ Tool usage guidance
✅ Reusable by any project
✅ NO project-specific references
✅ NO @CLAUDE/ doc references
✅ NO "dogfooding" language

**Examples**:
- `destructive_git` - Blocks dangerous git operations (generic)
- `tdd_enforcement` - Enforces test-first development (generic)
- `sed_blocker` - Blocks sed usage (generic)
- `eslint_disable` - Prevents ESLint suppressions (generic)

### Project Plugins (.claude/hooks/handlers/)

**Criteria**:
⚠️ Project-specific functionality
⚠️ Dogfooding language/concepts
⚠️ References @CLAUDE/ documentation
⚠️ Specific to developing this project
⚠️ NOT reusable by other projects

**Examples**:
- `dogfooding_reminder` - Reminds about bug handling protocol (project-specific)
  - References `@CLAUDE/CodeLifecycle/Bugs.md`
  - Uses "dogfooding" terminology
  - Only useful when developing hooks daemon itself

### How QA Agent Checks This

```bash
# Scan library handlers for violations
grep -r "@CLAUDE" src/claude_code_hooks_daemon/handlers/

# Check for dogfooding language
grep -r "dogfooding" src/claude_code_hooks_daemon/handlers/

# Manual review
# Read handler code - does it reference project-specific docs/concepts?
# Does it use terminology specific to this project?
# Would this handler be useful in other projects?
```

**If violations found**: Handler must be moved to plugin system.

---

## When to Run QA

### Always Required

- ✅ **Automated QA**: Before every commit
- ✅ **Automated QA**: After making code changes
- ✅ **Automated QA**: Before creating pull requests
- ✅ **Automated QA**: After merging branches

### Automated QA Only (Quick Check)

- Small bug fixes (single file)
- Documentation updates
- Configuration tweaks
- Trivial changes

### Automated + Sub-Agent QA (Full Review)

- New handlers or features
- Architectural changes
- Refactoring work
- Agent team deliverables
- Complex features

### Automated + Sub-Agent + Acceptance Testing (Pre-Release)

**Required before production releases:**
- ✅ New handler implementations
- ✅ Handler behavior changes
- ✅ Major features
- ✅ Release candidates
- ✅ After significant changes to core functionality

**Acceptance testing validates real-world scenarios with AI agents executing the test playbook.**

---

## QA Failure Handling

### Automated QA Fails

1. Read failure details in `/workspace/untracked/qa/*.json`
2. Fix issues
3. Run `./scripts/qa/run_autofix.sh` (for format/lint)
4. Re-run `./scripts/qa/run_all.sh`
5. Repeat until all pass

### Sub-Agent QA Fails

**QA Agent (Gate 2) Fails**:
- Developer must fix quality issues
- Re-run automated QA
- Restart from Gate 1 (Tester)

**Senior Reviewer (Gate 3) Rejects**:
- Developer must complete missing phases
- Address architectural issues
- Restart from Gate 1

**Honesty Checker (Gate 4) Rejects (THEATER)**:
- ENTIRE BRANCH REJECTED
- May require replanning
- Fix theater issues with proper implementation
- Restart from Gate 1

---

## Quick Reference

### Commands

```bash
# Run all automated QA
./scripts/qa/run_all.sh

# Auto-fix format and lint issues
./scripts/qa/run_autofix.sh

# Individual checks
./scripts/qa/run_format_check.sh
./scripts/qa/run_lint.sh
./scripts/qa/run_type_check.sh
./scripts/qa/run_tests.sh
./scripts/qa/run_security_check.sh
./scripts/qa/run_dependency_check.sh

# Daemon restart verification
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```

### Success Indicators

✅ All 7 automated checks pass
✅ Coverage ≥ 95%
✅ Daemon restarts successfully
✅ No security issues
✅ Library/plugin separation maintained
✅ Sub-agent QA approves (if required)

---

## See Also

- **CLAUDE/AcceptanceTests/GENERATING.md** - Complete acceptance testing guide (agentic execution)
- **CLAUDE/AgentTeam.md** - Agent team workflow with QA gates
- **CLAUDE/CodeLifecycle/Features.md** - Feature development with QA integration
- **CLAUDE/CodeLifecycle/Bugs.md** - Bug fix workflow with QA verification
- **CONTRIBUTING.md** - Contribution guidelines and QA standards

---

**Maintained by**: Claude Code Hooks Daemon Contributors
**Last Updated**: 2026-02-09
