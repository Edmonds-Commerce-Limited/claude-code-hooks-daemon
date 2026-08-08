# Plan 00201: Sensitive Content Secret-Word Blocking

**Status**: Complete
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A presentation-quality audit found employer/client identifiers leaked across
~160 places in this repo, including shipped source
(`untracked/resume-readiness/REDACTION-MAP.md`, `FINDINGS.md`). The redaction
itself is separate, tracked work. This plan is the guard that stops it
recurring: a `sensitive_content` PreToolUse blocking handler plus a
whole-tree QA backstop, gitignore rules landed first (Plan-adjacent commit
`02de0cf7`), and — the hard part — a **no-echo guarantee** for the secret
word list: once a term is in `.claude/block-words.secret`, it must never
appear in a deny reason, a daemon log, a payload-capture file, or a
transcript archive.

Two independent sources of blocked content:

- **(a) Public patterns** — named regexes declared in
  `.claude/hooks-daemon.yaml`, safe to name in messages (paths, non-placeholder
  home dirs, session UUIDs, profanity). The deny SHOULD say what matched.
- **(b) A secret word list** — plain text, gitignored, one term per line. The
  deny must NEVER reveal the term or its context — only a numeric index into
  the (gitignored, hence meaningless-without-it) file.

## Goals

- `sensitive_content` PreToolUse blocking handler: public-pattern matches
  reveal what matched; secret-list matches reveal only an index.
- Shared `utils/secret_redaction.py` utility (the ONE place that loads/matches
  the secret list) reused by the handler AND every leak vector below, so
  there is a single source of truth for "what counts as a secret term".
- Redact secret terms at every place raw hook content reaches disk or logs:
  `daemon/payload_capture.py`, `core/router.py`'s PreToolUse debug log,
  `core/front_controller.py`'s `log_error_to_file`, and
  `handlers/pre_compact/transcript_archiver.py`.
- `scripts/qa/check_sensitive_content.py` wired into `run_all.sh`: whole
  tracked-tree scan, same two sources, same no-echo rule, JSON output,
  non-zero exit on any hit.
- Tracked `.claude/block-words.secret.example` documenting the format (the
  real file cannot be tracked — it is itself the secret).
- Config-changes manifest entry; `get_claude_md()` + acceptance tests.

## Non-Goals

- The actual history redaction (renaming employer/client host and account
  identifiers to neutral placeholders such as `host-a` across the
  tree/history) — tracked separately per `REDACTION-MAP.md` /
  `REWRITE-PROCEDURE.md`, not this plan.
- A built-in, shipped-by-default `public_patterns` list for client projects.
  The four categories this repo cares about (vhosts paths, home dirs, session
  UUIDs, profanity) are configured in THIS repo's own
  `.claude/hooks-daemon.yaml` as a dogfood example; `public_patterns` defaults
  to an empty list for other projects (config is truth, nothing hardcoded).
- CI enforcement of the QA script — this repo has no CI yet (separate MT-2
  finding); `run_all.sh` wiring is the enforcement surface today.

## Threat Model (drives every design decision below)

A deny `reason` is shown to the user, written to the session transcript, and
may be pasted into a bug report or a GitHub issue. Anything that reaches a
deny reason, a log line, a capture file, or a transcript archive is
effectively public. The secret list itself is the only thing allowed to
"know" the actual terms; every other surface may know at most an index into
it (meaningless without the gitignored file) and a byte-count/line-count.

## Design Decisions

### D1: Shared redaction utility, not duplicated matching logic

`utils/secret_redaction.py` owns: resolving the configured secret-list path
(mirrors `payload_capture.resolve_capture_dir`'s parameter-driven shape),
loading+caching terms (mtime-keyed, missing file = empty set, no error),
literal case-insensitive matching (terms are `re.escape`d before use — a
term that is itself a regex metacharacter string like `a.b*c` must match
literally), and `redact_text`/`redact_structure` for the log/capture sites.
The handler and every low-level leak-vector site import this ONE module —
DRY, and it is the only code path that ever reads the raw terms.

### D2: Process-lifetime cache, not per-event I/O

`core/router.py`'s PreToolUse debug log fires on **every** PreToolUse event —
re-reading and re-parsing the secret file (or the daemon config, to resolve
an overridden path) on every event would be a real hot-path regression.
Config changes in this daemon are only ever picked up on restart (confirmed
convention — see `payload_capture.py`'s own docstring), so caching the
resolved path AND the loaded terms for the life of the process is exactly
the right lifetime, not a staleness bug. A `reset_cache()` test helper keeps
unit tests isolated from that process-lifetime cache.

### D3: New check, not bolted onto an existing content-scanner

`sensitive_content` is its own handler (not folded into
`security_antipattern`) because its no-echo obligation is categorically
different from every sibling content blocker — `security_antipattern` and
`qa_suppression` both name what they matched, which is the opposite of this
handler's secret-list behaviour. Mixing the two invariants in one handler
risks a copy-paste bug leaking a term through the code path built for the
other source.

## Tasks

### Phase 1: Redaction utility + handler (TDD)

- [x] ✅ **Task 1.1**: `utils/secret_redaction.py` — path resolution, cached
  term loading, literal case-insensitive matching, `redact_text`,
  `redact_structure`, `reset_terms_cache()`/`reset_active_path_cache()`.
  34 tests, TDD RED confirmed before implementation.
- [x] ✅ **Task 1.2**: `sensitive_content` PreToolUse handler — public
  patterns (named regex list from config, deny names the match) and secret
  list (deny names only an index). 24 tests, including direct
  `term not in result.reason` assertions for every secret-list scenario.
- [x] ✅ **Task 1.3**: dogfood `public_patterns` config in
  `.claude/hooks-daemon.yaml` (vhosts-path, non-placeholder-home-dir,
  session-uuid — profanity deliberately not populated, see journal).
  `.claude/block-words.secret.example` still pending (Phase 4).

### Phase 2: Close the leak vectors

- [x] ✅ **Task 2.1**: `daemon/payload_capture.py` — redact `hook_input`
  before writing the JSONL line. Test: a payload-capture round trip with a
  secret in the payload produces a capture file not containing the term.
- [x] ✅ **Task 2.2**: `core/router.py` PreToolUse debug log — redact before
  `logger.debug(...)`. Test: log output does not contain the term.
- [x] ✅ **Task 2.3**: `core/front_controller.py::log_error_to_file` — redact
  `hook_input` before writing to `hook-errors.log`.
- [x] ✅ **Task 2.4**: `handlers/pre_compact/transcript_archiver.py` — redact
  the transcript text before archiving.

### Phase 3: QA backstop

- [x] ✅ **Task 3.1**: `scripts/qa/check_sensitive_content.py` — whole
  tracked-tree scan (`git ls-files`), same two sources, `file:line` +
  rule-index reporting (never the term), JSON output matching sibling QA
  scripts, non-zero exit on any hit. Excludes `.claude/block-words.secret`
  itself from its own scan output by construction (it is gitignored, so
  `git ls-files` never lists it — verified by running it with the real file
  present, not assumed).
- [x] ✅ **Task 3.2**: Wired into both `run_all.sh` and `llm_qa.py`, and it went
  in **green** as intended — the gate landed with the redaction pass rather
  than before it, so it never blocked another commit's verification. Verified
  live: `sensitive_content: 0 violations` in the QA suite.
- [x] ✅ **Task 3.3**: Done, by Plan 00200's `qa-check-count-hardcoded` rule
  rather than by hand — the hardcoded counts in `CLAUDE.md`, `RELEASING.md` and
  `README.md` were replaced with "every check", so the runner is the single
  source of truth and the number cannot drift again. The concurrency worry was
  real and the two plans did land on the same lines; deferring to 00200's guard
  was the right call.

### Phase 4: Docs, manifest, verification

- [x] ✅ **Task 4.1**: Both present on the handler; the resident guidance names
  the two disclosure rules (public patterns are quoted, secret-list hits give
  only an index).
- [x] ✅ **Task 4.2**: `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.52.0.yaml`.
- [x] ✅ **Task 4.3**: `docs/guides/HANDLER_REFERENCE.md` entry present.
- [x] ✅ **Task 4.4**: QA 19/19, 11,139 tests, coverage 95.3%, daemon RUNNING.
- [x] ✅ **Task 4.5**: Live dogfood done end to end against the running daemon,
  and — per Task 5.4's lesson — against a **temp** list, never the operational
  one. A `Write` containing the sentinel term returned `deny`; the reason named
  only `entry 1 of 1`; and a scan of **every** file under `untracked/` (daemon
  log, payload captures, everything) found the term in **nothing**. Both halves
  of the contract hold: a handler that blocked the term but logged it would
  have moved the leak, not closed it. Afterwards the real list was confirmed
  byte-intact (12 entries), still gitignored and still untracked.

### Phase 5: Dogfooding fallout

- [x] ✅ **Task 5.0**: The handler blocked maintenance of its own word list.
  Found immediately on first real use: the initial `Write` lands (nothing is
  configured yet, so nothing matches), then every later `Edit` to add or
  correct an entry is denied — as `entry 8 of 10`, an index deliberately
  meaningless without the file you are being prevented from opening. The
  file whose entire purpose is to enumerate blocked terms was the one file
  that could not contain them. Fixed with `_is_secret_list_itself()`,
  resolving both sides to absolute paths (the config value is repo-relative;
  the tool always sends absolute). The tracked `.example` seed is
  deliberately NOT exempt — it ships, so a real term pasted there would be
  published. 4 tests, one of which is a control asserting the `.example`
  stays checked so the fix cannot pass by disabling matching wholesale.

- [x] ✅ **Task 5.1**: Redaction pass complete — 165 violations (35
  public-pattern, 130 secret-term) across 52 files, including shipped source,
  with 2 file renames and both reference-chased. Shipped together with Task 3.2
  so the gate landed green. The checker now reports **0 violations** over the
  whole tracked tree. Far more than the 55+ first projected, because the map
  counted term occurrences while the guard counts *lines*, and the secret word
  list caught families the hand-audit had missed.

- [x] ✅ **Task 5.2**: The `session-uuid` public pattern blocked the
  placeholder its own deny message recommended. It matched any UUID shape,
  so "use an all-zeros placeholder instead" was itself denied — the only
  advertised remediation was unusable, and the redaction could not be
  completed at all. Worse, the fix could not be typed into
  `.claude/hooks-daemon.yaml` until the pattern was relaxed, because the
  comment explaining it tripped the live rule. Now exempts UUIDs whose hex
  digits are all the same character (all-zeros, all-a, all-f). Uniformity is
  the test rather than "starts with zeros", so a near-miss with one odd
  digit is still caught. `tests/integration/test_sensitive_content_uuid_placeholders.py`
  reads the pattern out of the real config so deleting the lookahead fails
  the suite, and includes a control asserting real UUIDs are still matched.

- [x] ✅ **Task 5.3**: `today_only_mode` has no exemption for a SECURITY
  redaction of a historical journal day-file. Its premise is right for
  narrative — a correction belongs in a new dated entry — but appending "the
  15 July entry contained a real session UUID" does not remove the UUID. Used
  the handler's own supported config control (flip to `advise`, four edits,
  flip straight back, verified restored by probing the live daemon socket)
  rather than working around the check. Rationale recorded in the config; if
  it recurs the fix is a first-class `MUST_..._BECAUSE` escape hatch, not a
  standing relaxation.

- [x] ✅ **Task 5.4**: A live-dogfood step overwrote the operational
  `.claude/block-words.secret` with a single throwaway term. Nothing failed:
  the guard silently stopped guarding and the QA scanner began reporting a
  cleaner tree than reality — exactly the failure mode that would let a
  redaction be declared finished while identifiers remained. Restored by hand.

  Durable fix applied where it will actually be read: the rule now lives in the
  `safety_notes` of the very acceptance test that tempts an agent to touch the
  real list — point `secret_word_list_path` at a temp file, restart, test,
  restore — together with *why* (the failure is silent, so nothing will tell
  you). Guidance at the point of use, not a note in a plan nobody re-reads.

  No stronger guard is available and it is worth being explicit about why: the
  file is deliberately untracked and gitignored, so git cannot detect the
  overwrite, and it must stay hand-editable, so it cannot be made read-only.
  Task 4.5 was then executed under exactly this rule and the operational list
  was verified untouched afterwards.

## Success Criteria

- [x] ✅ Public-pattern deny messages name what matched; secret-list deny
  messages never contain the term or surrounding text — asserted directly in
  tests (86 passing across the handler, redaction utility, UUID-placeholder and
  response-log suites), and confirmed live in Task 4.5.
- [x] ✅ Every identified leak vector redacts secret terms before they reach
  disk/log, each with a round-trip test. **Five, not the four scoped**: the
  original list (payload capture, router debug log, front-controller error log,
  transcript archiver) missed the daemon's blocking-response debug log in
  `server.py`, found later by re-reading the log sites rather than trusting the
  list. Closed in `ceddf020`, with `60412be2` fixing the substring predicate
  that was mislabelling ordinary status renders as blocking responses — which
  is *how* an identifier reached a log about blocking decisions in the first
  place.
- [x] ✅ `scripts/qa/check_sensitive_content.py` scans the whole tracked tree
  (`git ls-files`) and is wired into both `run_all.sh` and `llm_qa.py`;
  currently 0 violations.
- [x] ✅ Missing/empty/comments-only secret file -> handler and redaction
  utility are both inert, no crash (covered in `test_secret_redaction.py`).
- [x] ✅ QA **19/19** (the count moved from 14 as the suite grew), daemon
  RUNNING, and the live dogfood confirmed both halves: the block fires, and the
  term is absent from every log and capture under `untracked/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00201-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Gitignore-first commit `02de0cf7` (landed before this plan folder existed,
  per the project's own ordering requirement — see task instructions).
- (implementation pending)
