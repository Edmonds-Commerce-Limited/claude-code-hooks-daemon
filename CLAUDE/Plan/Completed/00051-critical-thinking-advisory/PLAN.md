# Plan 051: Critical Thinking Advisory Handler (UserPromptSubmit)

**Status**: Complete
**Created**: 2026-02-12
**Owner**: TBD
**Priority**: Medium
**Estimated Effort**: 3-4 hours

## Overview

LLMs tend to be overly agreeable - they execute instructions without questioning whether the approach is optimal. This handler injects periodic advisory context on UserPromptSubmit events, encouraging the agent to critically evaluate user requests before blindly complying.

The goal is to catch XY problems, suggest better alternatives, and enable constructive pushback when the user's idea could be improved. Think of it as a "rubber duck that talks back."

**Critical design constraint**: This handler MUST NOT flood the context window. Most user prompts ("yes", "carry on", "do it") don't warrant critical thinking advice. The handler must be surgically targeted to only fire when it adds value.

## Goals

- Inject advisory context encouraging critical evaluation of user instructions
- Fire only on substantial prompts where critical thinking adds value
- Avoid flooding context on trivial prompts (confirmations, short replies)
- Use multiple filtering strategies to minimise wasted tokens
- Keep advisory message concise (3-5 lines max)

## Non-Goals

- Blocking any user actions (this is purely advisory)
- Replacing the user's judgment (just nudging toward critical thinking)
- Firing on every single prompt
- Long verbose messages that waste context

## Context & Background

### The Problem

When a user says "implement X using approach Y", most LLMs will immediately start implementing Y without considering whether Y is the best approach, or whether X is even the right thing to build. Common failure modes:

- **XY Problem**: User asks for Y (their attempted solution) when the real problem is X
- **Over-engineering**: User requests a complex solution when a simpler one exists
- **Wrong abstraction**: User suggests a pattern that doesn't fit the codebase
- **Missing context**: User doesn't know about existing utilities/patterns that already solve the problem

### Existing Infrastructure

- `UserPromptSubmit` event provides the `prompt` field (full user text)
- `HandlerHistory.total_count` provides a session-wide counter for frequency gating
- `SessionState` provides context pressure info (could skip when context is tight)
- Context-only response format: `HookResult(decision=ALLOW, context=[...])`
- Two existing UserPromptSubmit handlers: GitContextInjector (priority 20), HelloWorld (priority 5)

## Technical Design

### Triggering Strategy (Multi-Gate Filter)

The handler uses a **multi-gate filter** - ALL gates must pass for the advisory to fire. This ensures minimal context waste.

```
Gate 1: Prompt Length     (>= 80 chars)     → Skip trivial prompts
Gate 2: Random Sampling   (1-in-5 chance)   → Don't fire every time even on long prompts
Gate 3: Cooldown          (skip if fired     → Prevent back-to-back firing
                           within last 3
                           handler events)
```

**Why this combination:**

1. **Gate 1 (Length)** filters out ~60-70% of prompts immediately. Short prompts like "yes", "carry on", "do it", "looks good" are never worth advising on. The 80-char threshold catches most confirmations while allowing genuine task descriptions through.

2. **Gate 2 (Random)** ensures that even substantial prompts don't always get the advisory. 1-in-5 (20%) means roughly one advisory per 5 eligible prompts. This prevents the advisory from feeling repetitive.

3. **Gate 3 (Cooldown)** prevents clustering. Even with random sampling, you could get unlucky and fire twice in a row. The cooldown ensures at least 3 handler events between firings.

**Expected firing rate**: With ~30% of prompts being substantial and 20% random sampling, the handler fires roughly once every 15-20 prompts. That's about once every 10-15 minutes of active work - enough to be useful, rare enough to not annoy.

### Advisory Message

The message should be concise, varied, and non-preachy. Rotating through a small set of messages prevents staleness.

**Message pool** (randomly selected):

```
"Before executing: Is this the best approach, or could you suggest a better alternative? Consider whether the request has an XY problem - is the user asking for a solution when the real problem might be different?"

"Critical thinking check: Does this request make technical sense for the codebase? If you see a simpler or better approach, speak up - don't just comply."

"Pause and evaluate: Could this be done more simply? Is there existing code that already handles this? If the user's approach seems suboptimal, provide honest feedback before implementing."
```

Each message is 1-2 lines. No emoji, no headers, no formatting overhead.

### Handler Specification

```python
class CriticalThinkingAdvisoryHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CRITICAL_THINKING_ADVISORY,
            priority=55,  # After workflow handlers, before advisory
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._last_fired_count: int = -10  # Allow first fire
        self._rng = random.Random()  # Dedicated RNG instance

    def matches(self, hook_input: dict) -> bool:
        prompt = hook_input.get("prompt", "")
        return len(prompt) >= _MIN_PROMPT_LENGTH  # Gate 1: Length

    def handle(self, hook_input: dict) -> HookResult:
        dl = get_data_layer()
        current_count = dl.history.total_count

        # Gate 3: Cooldown
        if current_count - self._last_fired_count < _COOLDOWN_EVENTS:
            return HookResult(decision=Decision.ALLOW)

        # Gate 2: Random sampling
        if self._rng.random() > _FIRE_PROBABILITY:
            return HookResult(decision=Decision.ALLOW)

        self._last_fired_count = current_count
        message = self._rng.choice(_ADVISORY_MESSAGES)
        return HookResult(decision=Decision.ALLOW, context=[message])
```

### Constants

```python
_MIN_PROMPT_LENGTH: Final[int] = 80          # Gate 1: minimum chars
_FIRE_PROBABILITY: Final[float] = 0.2        # Gate 2: 1-in-5 chance (20%)
_COOLDOWN_EVENTS: Final[int] = 3             # Gate 3: minimum events between firings
_ADVISORY_MESSAGES: Final[tuple[str, ...]]    # Pool of rotating messages
```

### Priority: 55

- After workflow handlers (36-55 range) but at the tail end
- Before advisory handlers like British English (56-60)
- Non-terminal so it doesn't interfere with other handlers

## Tasks

### Phase 1: Design

- [ ] **Finalise message pool**
  - [ ] Write 3-5 concise advisory messages (1-2 lines each)
  - [ ] Ensure messages are varied and non-preachy
  - [ ] Review for token efficiency (shorter is better)

### Phase 2: TDD Implementation

- [ ] **Add constants**
  - [ ] Add HandlerID.CRITICAL_THINKING_ADVISORY to constants
  - [ ] Add priority constant

- [ ] **Write failing tests**
  - [ ] Test: Handler initialises with correct ID, priority, terminal=False
  - [ ] Test: matches() returns False for short prompts (< 80 chars)
  - [ ] Test: matches() returns True for long prompts (>= 80 chars)
  - [ ] Test: handle() returns ALLOW without context when random gate fails
  - [ ] Test: handle() returns ALLOW without context when cooldown active
  - [ ] Test: handle() returns ALLOW with context when all gates pass
  - [ ] Test: Context message is from the advisory message pool
  - [ ] Test: Cooldown resets after firing (tracks last_fired_count)
  - [ ] Test: Multiple calls respect cooldown window
  - [ ] Test: acceptance tests defined

- [ ] **Implement handler**
  - [ ] Create handler file
  - [ ] Implement matches() with length gate
  - [ ] Implement handle() with random + cooldown gates
  - [ ] Add advisory message pool
  - [ ] Verify all tests pass

### Phase 3: Integration

- [ ] **Register in config**
  - [ ] Add to hooks-daemon.yaml under user_prompt_submit
  - [ ] Set enabled: true, appropriate priority

- [ ] **Update constants modules**
  - [ ] Add HandlerID entry
  - [ ] Add Priority entry if needed

### Phase 4: QA & Verification

- [ ] **Run full QA suite**: `./scripts/qa/run_all.sh`
- [ ] **Restart daemon**: verify loads successfully
- [ ] **Dogfooding tests**: verify config integration
- [ ] **Live testing**: verify advisory appears occasionally on long prompts

## Dependencies

- None (standalone handler)

## Technical Decisions

### Decision 1: Multi-Gate Filter Over Single Strategy

**Context**: How to prevent context flooding while still firing usefully?

**Options Considered**:
1. **Length only** - Fire on all long prompts (too frequent)
2. **Random only** - Fire randomly regardless of prompt (wastes tokens on "yes")
3. **Cooldown only** - Fire periodically (no prompt awareness)
4. **Multi-gate** - Length AND random AND cooldown (surgical targeting)

**Decision**: Option 4 - Multi-gate filter

**Rationale**:
- Each gate independently eliminates a class of waste
- Combined effect is highly targeted (~1 in 15-20 prompts)
- Cheap to evaluate (string length, random float, integer comparison)
- Easy to tune individual gates without affecting others

### Decision 2: Instance-Level State Over Data Layer

**Context**: Where to store the cooldown counter?

**Options Considered**:
1. **HandlerHistory query** - Check when this handler last fired
2. **Instance variable** - Store `_last_fired_count` on handler instance
3. **Data layer custom state** - Add custom state to DaemonDataLayer

**Decision**: Option 2 - Instance variable

**Rationale**:
- Simplest implementation (just an int)
- Handler instance persists for daemon lifetime
- No need to query data layer on every call
- Cooldown doesn't need to survive daemon restarts
- HandlerHistory tracks decisions, not advisory context emissions

### Decision 3: Message Pool Size - 3-5 Messages

**Context**: How many advisory messages to rotate through?

**Decision**: 3-5 messages, randomly selected

**Rationale**:
- Too few (1-2) feels repetitive when it does fire
- Too many (10+) is over-engineering for an advisory
- 3-5 provides variety without maintenance burden
- Random selection prevents predictable cycling

## Success Criteria

- [ ] Handler fires approximately 1 in 15-20 prompts during normal work
- [ ] Never fires on short prompts (< 80 chars)
- [ ] Never fires back-to-back (cooldown enforced)
- [ ] Advisory messages are concise (< 300 chars each)
- [ ] All unit tests pass with 95%+ coverage
- [ ] Full QA suite passes
- [ ] Daemon loads successfully
- [ ] Live testing confirms occasional firing on substantial prompts

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Fires too often, annoying users | Medium | Low | Multi-gate filter with conservative defaults |
| Fires too rarely, never seen | Low | Medium | Tune thresholds; 80 chars + 20% + 3-event cooldown |
| Advisory messages feel patronising | Medium | Medium | Keep messages collaborative ("consider", "evaluate") not directive |
| Adds latency to prompt processing | Low | Low | All gates are O(1) operations, negligible overhead |
| Random behaviour makes testing hard | Medium | Medium | Seed RNG in tests for deterministic behaviour |

## Notes & Updates

### 2026-02-12
- Plan created based on user request for "critical thinking advisory"
- Key insight from user: must avoid flooding context, only fire on substantial prompts
- User suggested: prompt length threshold, random sampling (1-in-5 or 1-in-10), or combination
- Research confirmed: prompt text available in hook_input, HandlerHistory provides counters
- Designed multi-gate filter combining length + random + cooldown
