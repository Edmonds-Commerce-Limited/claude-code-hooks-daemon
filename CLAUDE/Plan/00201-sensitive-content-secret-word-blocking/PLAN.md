# Plan 00201: Sensitive Content Secret-Word Blocking

**Status**: In Progress
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

- The actual history redaction (renaming `host-a` -> `host-a` etc. across
  the tree/history) — tracked separately per `REDACTION-MAP.md` /
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

- [ ] ⬜ **Task 2.1**: `daemon/payload_capture.py` — redact `hook_input`
  before writing the JSONL line. Test: a payload-capture round trip with a
  secret in the payload produces a capture file not containing the term.
- [ ] ⬜ **Task 2.2**: `core/router.py` PreToolUse debug log — redact before
  `logger.debug(...)`. Test: log output does not contain the term.
- [ ] ⬜ **Task 2.3**: `core/front_controller.py::log_error_to_file` — redact
  `hook_input` before writing to `hook-errors.log`.
- [ ] ⬜ **Task 2.4**: `handlers/pre_compact/transcript_archiver.py` — redact
  the transcript text before archiving.

### Phase 3: QA backstop

- [ ] ⬜ **Task 3.1**: `scripts/qa/check_sensitive_content.py` — whole
  tracked-tree scan (`git ls-files`), same two sources, `file:line` +
  rule-index reporting (never the term), JSON output matching sibling QA
  scripts, non-zero exit on any hit. Excludes `.claude/block-words.secret`
  itself from its own scan output by construction (it is gitignored, so
  `git ls-files` never lists it — verified, not assumed).
- [ ] ⬜ **Task 3.2**: Wire into `scripts/qa/run_all.sh` (and `llm_qa.py`).
- [ ] ⬜ **Task 3.3** (opportunistic, only if trivial): correct the "10
  checks" claim in `CLAUDE.md:45` and `RELEASING.md` to match `run_all.sh`
  reality, per team-lead's heads-up — skip if Plan 00200 is actively editing
  those exact lines concurrently.

### Phase 4: Docs, manifest, verification

- [ ] ⬜ **Task 4.1**: `get_claude_md()` + `get_acceptance_tests()` on the
  handler.
- [ ] ⬜ **Task 4.2**: Config-changes manifest entry
  (`CLAUDE/UPGRADES/UNRELEASED/config-changes/`).
- [ ] ⬜ **Task 4.3**: `docs/guides/HANDLER_REFERENCE.md` entry.
- [ ] ⬜ **Task 4.4**: Full QA green, daemon restart -> RUNNING.
- [ ] ⬜ **Task 4.5**: Live dogfood — real `block-words.secret` with a
  nonsense term, Write containing it -> deny fires, term appears in no log
  and no payload-capture file (checked directly, not assumed).

## Success Criteria

- [ ] Public-pattern deny messages name what matched; secret-list deny
  messages never contain the term or surrounding text — asserted directly
  in tests, not just eyeballed.
- [ ] Every identified leak vector (payload capture, router debug log,
  front-controller error log, transcript archiver) redacts secret terms
  before they reach disk/log — each with a round-trip test.
- [ ] `scripts/qa/check_sensitive_content.py` scans the whole tracked tree
  and is wired into `run_all.sh`.
- [ ] Missing/empty/comments-only secret file -> handler and redaction
  utility are both inert, no crash.
- [ ] QA 14/14 (or current count), daemon RUNNING, live dogfood confirms the
  block fires and the term is absent from logs/captures.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00201-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Gitignore-first commit `02de0cf7` (landed before this plan folder existed,
  per the project's own ordering requirement — see task instructions).
- (implementation pending)
