# Plan 00529 Task 2c: implementation report, part 3 (daemon warning line, then handoff)

This report continues `261022-task-2c-impl-2-opus.md`, on branch `worktree-529-relay-loud-fallthrough`, starting from
head `9023fe8b2`. This agent passed its soft context budget after step 1. The brief says to stop at that point, so
the **Handoff** section below lists what is left.

## Step 1: one warning line on every relay-eligible answer (commit `b6928509c`, pushed)

- New module `src/claude_code_hooks_daemon/daemon/relay_unused_warning.py`:
  - `relay_unused_warning_text(binary)` returns `"WARNING: " + relay_binary_missing_warning(Path(binary), daemon_cli_command("transport", "on"))`. This is the same text that `status`, the status line and
    `relay_binary_checker` use.
  - `is_relay_eligible_event(EventType)` is derived from `EventIDMeta.relay_eligible`.
  - `add_relay_unused_warning(response, event, binary)` returns a deep copy with the line appended.
- **Channel.** The line goes to `hookSpecificOutput.additionalContext` when the event's response schema
  (`RESPONSE_SCHEMAS`) declares that field. Otherwise it goes to the top-level `systemMessage`.
- `DaemonController.process_request` calls this through `_warn_if_relay_unused` after `to_json`.
  - `HookEvent` drops unknown fields (pydantic `extra='ignore'`), so the marker is read from `request_data`.
  - An empty or absent marker adds nothing.
  - A non-string marker, or a marker on an event with no relay guard, is logged at ERROR. The verdict comes back
    unchanged.

### Deviation from the ruling, with evidence

The ruling (task 3) and the previous handoff said to `add_context` on the `HookResult`. That would have changed a
verdict. A PermissionRequest ALLOW with context serialises to `decision.behavior = "allow"`, so a silent "no
opinion" becomes an approval:

```
silent:      {}
add_context: {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': {'behavior': 'allow'}, 'additionalContext': 'WARNING: x'}}
```

The line is therefore added to the serialised response, and only ever as a text key.
`test_every_eligible_event_carries_the_line_and_keeps_its_decision` checks every relay-eligible event in three
cases: silent allow, allow with context, and deny where the event can express one. In each case it compares the
response with the text-only keys removed (`systemMessage`, `additionalContext`, `hookEventName`), and it
re-validates the warned response against the event's schema.

**Known limit.** On a PreToolUse `defer`, Claude Code ignores `additionalContext`, so the warning is carried but
not delivered. The schema allows no other field there.

### Red, then green

Module absent: `ModuleNotFoundError: No module named 'claude_code_hooks_daemon.daemon.relay_unused_warning'`.

With the module present and HEAD's `controller.py` swapped back in:

```
E       KeyError: 'hookSpecificOutput'                    [allow]
E       KeyError: 'additionalContext'                     [deny, ask]
E       AssertionError: assert 'relay_unused' in ''       [non-string marker logs]
4 failed, 3 passed
```

Green: 98 passed in `tests/unit/daemon/test_relay_unused_warning.py`. With `test_controller.py`,
`test_controller_degraded_mode.py` and `test_server_coverage.py`: 205 passed. mypy is clean on both source files,
and `run_autofix.sh` was applied before the commit.

## Handoff: what is left

1. **Detached session-start repair (ruling task 4).**
   - Model it on `src/claude_code_hooks_daemon/install/background_sync.py` (state files and lock).
   - Key a state file by binary path, `relay_binary_defect(binary)` reason and daemon version, so each cause is
     attempted once. Take a lock so two sessions never build at once.
   - The child runs `ensure_relay_binary` (`transport_toggle.py`) plus `regenerate_deployed_hooks`, the
     `transport on` routine without the toggle.
   - Start it detached from `handlers/session_start/relay_binary_checker.py` when its predicate fires. Never run
     it in the foreground: the build timeout is 300 s.
   - Add to the checker's warning: "repair started in the background; if the next session still warns, run
     `transport on`".
   - A spawn failure must be reported, not swallowed. Inject `run_fn`/`fetch_fn`/spawn in tests, as the
     `relay_deploy` tests do.
2. **Docs.**
   - `CLAUDE/Worktree.md` around lines 108-121, and the transport docs: "a missing or broken relay never changes
     a verdict; every answer says so until `transport on`".
   - Mention the PermissionRequest finding above.
3. **Release note.**
   - Use `CLAUDE/UPGRADES/UNRELEASED/release-notes/019-<slug>.md`. origin/main holds up to 018 (checked at
     `b6928509c`). Re-check before committing.
4. **Wrap-up.**
   - Tick Task 2c in PLAN.md only when all of its text is delivered.
   - Run targeted QA once:
     `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped`.
   - QA autofixes rewrite files, so commit them.
5. **Coordinator's full gate.** Targeted QA could not map tests to 8 files: `init.sh`, the forwarders,
   `constants/protocol.py`, `install/relay_deploy.py` and `install/transport_toggle.py`. The coordinator's full gate
   must cover them.

QA for this part: none run yet. Targeted QA runs once, after steps 1 to 3 of this handoff are done.
