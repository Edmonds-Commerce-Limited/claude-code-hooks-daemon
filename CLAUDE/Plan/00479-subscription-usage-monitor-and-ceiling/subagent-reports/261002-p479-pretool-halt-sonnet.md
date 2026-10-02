# Plan 00479 Task 4.2 prerequisite: PreToolUse deny that halts the turn

## Vendored contract (verified)

`remote-docs/code.claude.com/docs/en/hooks.md`:

- line 959: "**Universal fields** like `continue` are listed in the table below. Every event accepts them, but some events discard them..."
- line 965: "`continue` | `true` | If `false`, Claude stops processing entirely after the hook runs. Takes precedence over any event-specific decision fields"
- line 966: "`stopReason` | none | Message shown to the user when `continue` is `false`..."
- line 977: "For `PreToolUse` and `PostToolUse` hooks, the stop applies even when the tool call fails or completes while Claude is still streaming a response."

## Files changed

- `src/claude_code_hooks_daemon/core/response_schemas.py` (~line 26): `PRE_TOOL_USE_SCHEMA` gains top-level `continue` (boolean) and `stopReason` (string); `additionalProperties: False` kept.
- `src/claude_code_hooks_daemon/core/hook_result.py`: new `HookResult.halt_turn: bool = False` and `stop_reason: str | None` (line ~264); `validate_halt_request` model validator (line ~297, halt needs DENY, stop_reason needs halt); `_format_pre_tool_use_response` emits `continue: False` and `stopReason` (line ~695). No existing HookResult field carried continue/stopReason for other events (those derive it from DENY in `_format_continue_false_response`), so these are the minimal new fields.
- `src/claude_code_hooks_daemon/core/result_types.py`: `GatingResult.deny_and_halt(reason, *, stop_reason=None, context=None)`.
- `src/claude_code_hooks_daemon/core/chain.py`: `_carry_halt_request`, called from `carry_accumulated_fields` (used by both `HandlerChain` via `_assemble_final_result` and `FrontController`).
- `CLAUDE/HANDLER_DEVELOPMENT.md`: "Deny and halt the turn" subsection under Result Options.
- `tests/unit/core/test_pre_tool_use_halt_turn.py`: new.

## Handler API

```python
return GatingResult.deny_and_halt("Tool denied while paused", stop_reason="Paused until resume")
```

`stop_reason` defaults to the raw deny reason (without the daemon's continuation suffix). A plain deny/allow response is unchanged (pinned by tests).

## Combination

The chain merge is first-restrictive-wins. `_carry_halt_request` takes the first matched result with `halt_turn` and applies it to the winner whatever won: a deny winner keeps its own reason and gains halt plus stop reason; an ask/defer winner is replaced by the halting deny (decision and reason), since a deny outranks it. Covered: earlier advisory allow, earlier plain deny, earlier ask, collect-all mode. A terminal deny that ends the chain naturally prevents later handlers running (existing behaviour).

## Tests and QA

- `tests/unit/core` full directory: 2444 passed. New file covers schema accept/reject, serialisation, byte-pinned plain deny and allow, fail-fast validation, and the four combination cases.
- `scripts/qa/check_input_contract.py` exit 0; `scripts/qa/check_hook_contract.py` exit 0 (30 allowlisted gaps, no new ones).
- ruff, black (py311), mypy on the 5 touched python files: clean (black initially flagged my trailing comma in response_schemas.py; fixed).
- pyright: standalone invocation cannot resolve the venv (config lsp-venv path); the llm_qa pyright step passed instead (0 errors, 2089 files).
- `llm_qa.py changed`: 35/37 passed, 2 reported failed, neither from this change:
  - `docs_qa`: 3 advise-level `duplicate-block` findings, all in the Plan 00479 `PLAN.md` (lines 34-43, 51-55, 192-194), a file this change did not touch.
  - `changed_tests`: 4608 passed, 0 failed; the run is marked failed only because `chain.py`, `hook_result.py` (and two more src files) are "unmapped [too-broad]" in `scripts/qa/changed_tests_map.yaml`, which needs `--allow-unmapped` or a map rule (not added: no allowlist entries were permitted).
