# Contract delta: upstream hooks docs, audited 2.1.252 → 2.1.263

Supporting document for Phase 1 (Tasks 1.1 and 1.2), produced under Plan 00362
Task 2.11. It bounds the worklist for the verified extraction: which upstream
sections changed between the two audited states of
`https://code.claude.com/docs/en/hooks.md`, and what each of the 33 vendored
schemas claims against the refreshed text.

## Capture provenance

| State            | `docs_sha256`                                                      | Bytes   | Claude Code |
| ---------------- | ------------------------------------------------------------------ | ------- | ----------- |
| Last audited     | `d514bf57cec0424a8aa06b4fd4172ccd256a8cd0d8ed6144a4a61908ab901a6e` | 316 963 | 2.1.252     |
| This audit       | `c30a50b8192dadf4e6ba016e451685f57a6d1d2c360d268887a9a94022d29f3e` | 317 632 | 2.1.263     |
| Phase 3 re-check | `ac2f68e8221903ea4e3fc9e287959da2e979c0e7da95681c34cf5f8d7b36d28a` | 317 650 | 2.1.263     |

The refreshed text was captured with
`bin/hooks-daemon remote-docs add <url> --verbatim` (`fidelity: verbatim`,
`fetch_method: https-get`); the response body, with the provenance frontmatter
stripped, hashes to the `source_sha256` the capture recorded, which is the
value written to `META.json`. The capture itself is kept untracked
(`untracked/hooks-raw.md`), as Task 1.1 requires; the `e2462deb…` hash the
plan Overview quotes was an intermediate upstream state between the two rows.

A `diff -u` of the two raw texts is 42 lines: four prose hunks, no heading
added or removed, and no change to the `#### Decision control` table or to
any event's decision-control / output section.

The third row is what `hooks-daemon contract-status` (Task 3.2) found on its
first real run, later the same day: upstream had moved 18 bytes past the
`c30a50b8…` capture. The whole delta is hunk 5 below — one link retargeted in
ConfigChange prose — so `META.json` carries the `ac2f68e8…` hash and the
version stays 2.1.263, which is still the installed Claude Code.

## Changed sections

| #   | Upstream section                                 | Change (verbatim upstream text where the claim is affected)                                                                                                                                                                                                                                                                            | Contract effect                                                                             |
| --- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | `#### PermissionRequest input`                   | `permission_suggestions` is now "the permission updates Claude Code suggests for this request, such as adding an allow rule or changing the permission mode", and "the array isn't an exact list of the options you see" in the dialog. Previously: "the 'always allow' options the user would normally see in the permission dialog". | none — the schema records the field's shape via `input_example`, not the dialog equivalence |
| 2   | PermissionRequest `setMode` note                 | Reworded: bypass availability now cites "user, `--settings`, or managed settings" for `permissions.defaultMode`; the `disableBypassPermissionsMode` / restricted-mode no-op is now its own sentence; "`bypassPermissions` is never persisted as `defaultMode`" is unchanged.                                                           | none — no schema claims a `setMode` semantics                                               |
| 3   | PermissionRequest `updatedPermissions` paragraph | Now: "A hook can echo one of the `permission_suggestions` it received as its own `updatedPermissions` output." The trailing "which is equivalent to the user selecting that 'always allow' option in the dialog" was removed.                                                                                                          | none — `updatedPermissions` remains `allow only`                                            |
| 4   | `### DirectoryAdded`, "does not fire" list       | Now: "You add a directory that is already a working directory or inside one". Previously: "You add a directory that is already a working directory; the add fails with an error".                                                                                                                                                      | none — the schema's note ("the add has already completed when the hook runs") still holds   |
| 5   | `### ConfigChange`, WSL paragraph                | Link target only: "On WSL with [`wslInheritsWindowsSettings`](/docs/en/settings-reference#wslinheritswindowssettings), it also applies a changed Windows-side managed settings file on its policy poll without running them." Previously linked `/docs/en/settings#available-settings`; the sentence text is unchanged.                | none — no schema claims a settings-reference anchor                                         |

None of the five hunks touches a sentence any vendored claim was derived from.
Hunks 1–3 narrow what a consumer may INFER about the permission dialog from
`permission_suggestions`; the daemon's only consumer (`auto_approve_reads`)
reads the array's shape and does not reason about the dialog.

## Per-event verdicts

Every event heading in the refreshed text (33) has a vendored file, and every
vendored file has a heading; there is no NEW-UPSTREAM event. For each row the
claims compared are: `block_mechanism`, `can_block`, `ask_capable`,
`top_level_decision_enum`, the `hook_specific_output_fields` keys (and their
enums), `discarded_fields`, and the `input_example`.

| Event                 | Block mechanism              | Blocks | Ask | Decision enum | Hook-specific output fields                                                                          | Discarded                                                     | Verdict                                                         |
| --------------------- | ---------------------------- | ------ | --- | ------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------- |
| `ConfigChange`        | top-level-decision           | yes    | no  | block         | none                                                                                                 | systemMessage, continue                                       | UNCHANGED (section prose changed, hunk 5; no claim affected)    |
| `CwdChanged`          | none                         | no     | no  | —             | watchPaths                                                                                           | continue                                                      | UNCHANGED                                                       |
| `DirectoryAdded`      | none                         | no     | no  | —             | none                                                                                                 | continue                                                      | UNCHANGED (section prose changed, hunk 4; no claim affected)    |
| `Elicitation`         | hook-specific-action         | yes    | no  | —             | action, content                                                                                      | systemMessage, continue                                       | UNCHANGED                                                       |
| `ElicitationResult`   | hook-specific-action         | yes    | no  | —             | action, content                                                                                      | systemMessage, continue                                       | UNCHANGED                                                       |
| `FileChanged`         | none                         | no     | no  | —             | watchPaths                                                                                           | continue                                                      | UNCHANGED                                                       |
| `InstructionsLoaded`  | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue                                       | UNCHANGED                                                       |
| `MessageDisplay`      | none                         | no     | no  | —             | displayContent                                                                                       | systemMessage, continue                                       | UNCHANGED                                                       |
| `Notification`        | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue                                       | UNCHANGED                                                       |
| `PermissionDenied`    | none                         | no     | no  | —             | retry                                                                                                | —                                                             | UNCHANGED                                                       |
| `PermissionRequest`   | decision-behavior            | yes    | no  | —             | decision {behavior allow/deny, updatedInput, updatedPermissions, message, interrupt}                 | —                                                             | UNCHANGED (section prose changed, hunks 1–3; no claim affected) |
| `PostCompact`         | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue                                       | UNCHANGED                                                       |
| `PostModelSwitch`     | none                         | no     | no  | —             | none                                                                                                 | —                                                             | UNCHANGED                                                       |
| `PostToolBatch`       | top-level-decision           | yes    | no  | block         | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `PostToolUse`         | top-level-decision           | yes    | no  | block         | additionalContext, classifierContext, updatedToolOutput, updatedMCPToolOutput                        | —                                                             | UNCHANGED                                                       |
| `PostToolUseFailure`  | top-level-decision           | yes    | no  | block         | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `PreCompact`          | top-level-decision           | yes    | no  | block         | none                                                                                                 | systemMessage, continue                                       | UNCHANGED                                                       |
| `PreModelSwitch`      | permission-decision          | yes    | yes | block         | permissionDecision, permissionDecisionReason                                                         | updatedInput, additionalContext                               | UNCHANGED                                                       |
| `PreToolUse`          | permission-decision          | yes    | yes | —             | permissionDecision {allow/deny/ask/defer}, permissionDecisionReason, updatedInput, additionalContext | —                                                             | UNCHANGED                                                       |
| `SessionEnd`          | none                         | no     | no  | —             | none                                                                                                 | systemMessage                                                 | UNCHANGED                                                       |
| `SessionStart`        | none                         | no     | no  | —             | additionalContext, initialUserMessage, sessionTitle, watchPaths, reloadSkills                        | —                                                             | UNCHANGED                                                       |
| `Setup`               | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue, hookSpecificOutput.additionalContext | UNCHANGED                                                       |
| `Stop`                | top-level-decision           | yes    | no  | block         | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `StopFailure`         | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue, stopReason                           | UNCHANGED                                                       |
| `SubagentStart`       | none                         | no     | no  | —             | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `SubagentStop`        | top-level-decision           | yes    | no  | block         | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `TaskCompleted`       | exit-2-or-continue-false     | yes    | no  | —             | none                                                                                                 | —                                                             | UNCHANGED                                                       |
| `TaskCreated`         | exit-2-or-top-level-decision | yes    | no  | block         | none                                                                                                 | continue                                                      | UNCHANGED                                                       |
| `TeammateIdle`        | exit-2-or-continue-false     | yes    | no  | —             | none                                                                                                 | —                                                             | UNCHANGED                                                       |
| `UserPromptExpansion` | top-level-decision           | yes    | no  | block         | additionalContext                                                                                    | —                                                             | UNCHANGED                                                       |
| `UserPromptSubmit`    | top-level-decision           | yes    | no  | block         | additionalContext, sessionTitle                                                                      | —                                                             | UNCHANGED                                                       |
| `WorktreeCreate`      | path-return                  | yes    | no  | —             | worktreePath                                                                                         | systemMessage, continue                                       | UNCHANGED                                                       |
| `WorktreeRemove`      | none                         | no     | no  | —             | none                                                                                                 | systemMessage, continue                                       | UNCHANGED                                                       |

The verdict basis for a row not named in a hunk is the diff itself: an
unchanged section cannot have changed a claim derived from it. The three rows
whose sections did change were re-read in full against their JSON.

## QA state after the refresh

- `./scripts/qa/llm_qa.py hook_contract`: 0 violations, 30 allowlisted gaps,
  none stale.
- `./scripts/qa/llm_qa.py input_contract`: 0 violations, 3 allowlisted gaps,
  none stale.
- `tests/unit/qa/test_check_hook_contract.py::TestMetaProvenance` pins the
  audited version, hash and byte count, and that `event_count` equals the
  number of vendored files.

## Observations that are not contract findings

- `core/input_schemas.py` marks `permission_suggestions` as `required` on the
  PermissionRequest input schema, while the docs (both states) call it "an
  optional `permission_suggestions` array". The example always carries it and
  `additionalProperties` is permissive, so no live payload is rejected; it is
  a read-surface strictness question for Plan 00273's inventory, not a claim
  this delta introduced.
- Hunk 4 widens when `DirectoryAdded` does NOT fire (a directory "inside" an
  existing working directory). No daemon handler assumes the previous
  behaviour.
