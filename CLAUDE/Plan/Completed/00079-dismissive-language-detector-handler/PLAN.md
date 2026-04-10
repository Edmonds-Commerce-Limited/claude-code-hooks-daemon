# Plan 00079: DismissiveLanguageDetectorHandler

**Status**: Complete (2026-03-09)

## Context

LLMs frequently dismiss issues they encounter with cop-out language like "This is a pre-existing issue unrelated to our changes" instead of offering to fix them. This is almost always avoidance behaviour - the LLM doesn't want to do the work. The user's expectation is that issues get fixed, not explained away.

The only valid exceptions are: (1) user explicitly asked to stay focused on a single feature, or (2) user is running multiple agents concurrently. The handler's advisory message accounts for these by telling the agent to only defer if the user explicitly asked.

## Approach

Create a new **Stop** event handler following the exact pattern of `HedgingLanguageDetectorHandler`. It reads the last assistant message from the transcript via `TranscriptReader`, scans for dismissive regex patterns, and injects an advisory system-reminder telling the agent to offer to fix issues instead of dismissing them.

**No Strategy Pattern needed** - this is language-agnostic (natural language, not code).
**No throttling needed** - pattern matching IS the gate (unlike CriticalThinkingAdvisory).

## Files to Modify

### 1. Constants: `src/claude_code_hooks_daemon/constants/handlers.py`

- Add `DISMISSIVE_LANGUAGE_DETECTOR` to `HandlerID` class (after `HEDGING_LANGUAGE_DETECTOR` at line 426)
- Add `"dismissive_language_detector"` to `HandlerKey` literal (after `"hedging_language_detector"` at line 483)

### 2. Constants: `src/claude_code_hooks_daemon/constants/priority.py`

- Add `DISMISSIVE_LANGUAGE_DETECTOR = 58` in the Advisory range (56-60), after `CRITICAL_THINKING_ADVISORY = 55`

### 3. New handler: `src/claude_code_hooks_daemon/handlers/stop/dismissive_language_detector.py`

Follow `hedging_language_detector.py` structure exactly. Four pattern categories:

**"Not our problem"** (~11 patterns):

- `pre-existing issue/problem`, `not caused by our/my changes`, `unrelated to our/my/what we're`, `existed before our changes`, `was already there/present/broken/failing`, `not our problem/issue/concern/fault/bug`, `not something we introduced/caused/broke`

**"Out of scope"** (~7 patterns):

- `outside (the) scope of`, `beyond (the) scope of`, `out of scope`, `separate concern`, `separate issue`, `not within/in scope`, `falls outside`

**"Someone else's job"** (~6 patterns):

- `not our responsibility/work/task/job`, `not my/our area/domain`, `different task entirely`, `someone else's/should`, `a different effort/initiative/project`, `not what we're here/working on/doing/tasked`

**"Defer/ignore"** (~8 patterns):

- `can be addressed/fixed/handled/resolved later/separately`, `leave that/this/it for now/later`, `tackle that/this separately`, `defer that/this to/for`, `not worth fixing/addressing/worrying`, `ignore that/this for now`, `best left alone/as-is`, `let's not worry/concern ourselves about/with`

Advisory message template:

```
DISMISSIVE LANGUAGE DETECTED: {matched phrases}

Don't dismiss issues as someone else's problem.
If you encountered an error, test failure, or quality issue:

  1. ACKNOWLEDGE the problem clearly
  2. ASK the user: "I found [issue]. Want me to fix it?"
  3. NEVER assume it's pre-existing or out of scope without evidence

The user expects you to FIX problems, not explain them away.
Only defer if the user explicitly asks you to stay focused on something else.
```

### 4. Export: `src/claude_code_hooks_daemon/handlers/stop/__init__.py`

- Add import and `__all__` entry for `DismissiveLanguageDetectorHandler`

### 5. Config: `.claude/hooks-daemon.yaml`

- Add under `stop:` section (after `hedging_language_detector` at line 311):

```yaml
    dismissive_language_detector:
      enabled: true
      priority: 58
```

### 6. New test: `tests/unit/handlers/stop/test_dismissive_language_detector.py`

Follow `test_hedging_language_detector.py` pattern exactly. Reuse `_make_transcript`, `_assistant_message`, `_human_message` helpers.

**Test classes:**

- `TestDismissiveLanguageDetectorInit` - handler_id, non_terminal, tags, priority
- `TestDismissiveLanguageDetectorMatches` - positive cases per category (~25 tests), case insensitivity, negative cases (~10 tests: clean responses, no transcript, empty transcript, stop_hook_active, human-only messages)
- `TestDismissiveLanguageDetectorHandle` - ALLOW decision, context contains DISMISSIVE, context tells to fix, matched phrases in output, fallback when no transcript
- `TestDismissiveLanguageDetectorEdgeCases` - non-message types, malformed JSONL, OSError, empty lines
- `TestDismissiveLanguageDetectorAcceptanceTests` - has tests, tests have titles

## TDD Sequence

1. Add constants (HandlerID, Priority, HandlerKey)
2. **RED**: Write test file - all tests fail (handler doesn't exist)
3. **GREEN**: Write handler - all tests pass
4. **Integration**: Add `__init__.py` export + config entry
5. **Verify**: Daemon restart + status check
6. **QA**: `./scripts/qa/run_all.sh`

## Verification

```bash
# Tests pass
pytest tests/unit/handlers/stop/test_dismissive_language_detector.py -v

# Daemon loads successfully
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: RUNNING

# Full QA
./scripts/qa/run_all.sh
# Expected: ALL CHECKS PASSED
```
