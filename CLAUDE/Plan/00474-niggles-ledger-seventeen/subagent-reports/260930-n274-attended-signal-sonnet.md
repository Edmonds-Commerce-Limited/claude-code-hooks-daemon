# N274: AskUserQuestion denied as unattended while a human is typing

## Root cause

`ask_user_question_blocker` decides "unattended" from its `mode` option alone
(`mode: unattended`, declared in `hooks-daemon.yaml`, read as `self._mode`). The
mode branch in `handle()` returned DENY before looking at the hook input, so
nothing about the session, the transcript or the last prompt was consulted. The
module docstring says the daemon "cannot detect" attendance because no hook
event carries a flag; that is true of the event, but the session transcript
does record every prompt with a timestamp, a session id and an `origin.kind`.

The existing "real prompt versus tick" classification is split in two places:
`failsafe_cron_blockage_suppressor` treats a prompt as the owner when it carries
no `[tick:...]` sentinel (`utils/cron_tick.py`), and the skill-opportunity scan
(`skill_scan/constants.py`, `skill_scan/extraction.py`) excludes machine traffic
by flags (`isMeta`, `isSidechain`, ...) and content markers (ticks,
`ccy-supervisor`, `<teammate-message`, `<task-notification`, ...). The fix
reuses the second, which is the superset.

## Change

- `utils/human_presence.py` (new): `human_prompt_within(transcript, session_id, now, window)` reads the last 1 MiB of the transcript, finds the latest
  genuine human prompt of this session and checks its age. Reuses
  `EXCLUDE_FLAGS`, `EXCLUDE_CONTENT_MARKERS` and `is_genuine_text` (made public
  in `skill_scan/extraction.py`). Also requires `origin.kind == "human"` when the
  field is present (observed kinds in real transcripts: `human`,
  `task-notification`, `peer`, `auto-continuation`); absent means markers only.
- Handler: under `mode: unattended`, a human prompt within
  `human_presence_minutes` (default 30, `0` disables) is judged by strict
  mode's rules (prefix required), not waved through (review round 1). The deny
  now appends "Judged: mode is unattended, and there is no genuine human prompt
  in this session in the last N minutes ...".
- Window: 30 minutes rides out a meeting without treating an owner who left for
  the night as present. Configurable.
- Docs: `HANDLER_REFERENCE.md` option row, handler docstring and CLAUDE.md
  guidance, NIGGLES.md N274 status, release note 192.

## Tests

`tests/unit/utils/test_human_presence.py` (36) and
`tests/unit/handlers/pre_tool_use/test_ask_user_question_blocker_human_presence.py`
(15): recent human allows; old denies; recent tick, supervisor line, teammate
message, task notification, peer message and flagged records do not count; a
recent tick neither renews nor hides a human prompt; another session's prompt
does not count; missing, empty, garbage and oversized transcripts fail closed.
Red run captured before implementation (ModuleNotFoundError on the new module).

## Limits

- A prompt buried under more than 1 MiB of later transcript reads as absent
  (deny, the project's declaration stands).
- Only plain-string prompt content counts; a prompt with attached images is a
  list of blocks and is not recognised.
- The deployed acceptance probes carry no transcript, so they still see DENY.

## QA

- pytest by path: test_human_presence.py 36 passed; the new handler test file 15
  passed; test_ask_user_question_blocker.py 43 passed.
- ruff, black (`--target-version py311`), mypy on the three source files:
  clean. `audit_error_hiding.py` exit 0 (first draft had 2 findings, fixed in
  code, no exclusions). `check_input_contract.py` exit 0.
- `llm_qa.py changed --base main --allow-unmapped`, first run: 27/28 passed;
  changed_tests 2033 passed, 0 failed, 5 skipped (20 test files); the one
  failure was pyright, 5 errors, all in the two new test files (attribute
  assigned outside the class, `**{flag: True}` typing). Fixed; pyright on the
  four touched files then exits 0.
- Second full `llm_qa.py changed` run did NOT complete: it waited the whole
  3600 s for the host-wide QA lock and gave up. So the post-fix 28/28 is
  unverified; the pyright fix is verified only by targeted pyright plus the
  re-run pytest files. `skill_scan/extraction.py` is reported unmapped
  ([too-broad]); the full gate must cover it (only a rename of a private
  helper to public).
