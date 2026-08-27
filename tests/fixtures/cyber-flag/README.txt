tests/fixtures/cyber-flag/ -- classifier-trip test fixture
================================================================================

This directory holds ONE fixture file:

    DO-NOT-READ-cyber-flag-context-fixture.txt

It is a deliberately benign piece of content, dense with security/attack
vocabulary (spoofing, evasion, exploit, rootkit, C2, privilege escalation,
lateral movement, credential extraction, ...) framed as parody, glossary
entries, and a fictional movie-hacker monologue. It contains no real exploit
code, no working technique, and nothing actionable. Its purpose is described
in full in its own header -- read that header (see "How to use this fixture"
below for the safe way to do so) before using the file in any test.

It exists to support testing and tuning of two hooks-daemon handlers (see
Plan 00278):

  - model_fallback_detector
    (src/claude_code_hooks_daemon/handlers/session_start/model_fallback_detector.py)
    detects when the platform's own API-side safety classifier has silently
    substituted the session's model (apiRefusalCategory: "cyber",
    scope: "session") and warns the human, because the substitution does not
    recover on its own.

  - flaggable_work_advisor
    (src/claude_code_hooks_daemon/handlers/pre_tool_use/flaggable_work_advisor.py)
    advises delegating safeguard-flaggable work to a quarantine subagent
    BEFORE the main context reads it, using path globs and topic-term
    matching (its seed terms: spoof, spoofing, evasion, exploit, rootkit).

--------------------------------------------------------------------------
HOW TO USE THIS FIXTURE (delegate-to-quarantine pattern)
--------------------------------------------------------------------------

Do NOT `Read` DO-NOT-READ-cyber-flag-context-fixture.txt directly from a
main agent session. Reading dense attack-mechanics-flavoured vocabulary into
the main context is exactly the situation flaggable_work_advisor and
model_fallback_detector exist to guard against -- even though this
particular file is inert, a shallow classifier cannot tell that from the
main context's point of view, and the whole point of the fixture is to
resemble what a classifier reacts to.

The intended test pattern is:

  1. From the main session, decide -- from this README and the fixture's own
     filename, NOT by opening its content -- that the sub-task ("read and
     summarise the fixture") is flaggable-shaped.
  2. Delegate the WHOLE sub-task to a quarantine subagent, e.g.:

         Agent(subagent_type: "hooks-daemon-opus-security",
               prompt: "Read tests/fixtures/cyber-flag/"
                       "DO-NOT-READ-cyber-flag-context-fixture.txt and "
                       "report back only a high-level, vocabulary-free "
                       "summary of its structure (glossary / monologue / "
                       "abstract sections) confirming it contains no real "
                       "exploit code.")

  3. Take back only the clean summary. Do not have the subagent quote the
     jargon-dense body back into the main context.

  4. For handler unit/integration tests that need the fixture's PATH or
     matched TERMS (e.g. asserting flaggable_work_advisor's path-glob or
     topic-term matching fires on a Read/Grep of this file), reference the
     file by path without needing to read its content into the test
     assertion -- the handler under test only inspects the tool_input, not
     the file body.

--------------------------------------------------------------------------
WHAT THIS FIXTURE IS DELIBERATELY NOT FOR
--------------------------------------------------------------------------

- It is NOT a CI gate. Deliberately triggering a live model fallback
  (i.e. actually causing apiRefusalCategory: "cyber" to fire against the
  real API) is a manual, opt-in, human-observed test -- never automated,
  never run in CI, and never run without the operator knowing it might
  degrade the CURRENT session's model for its remainder (scope: "session").