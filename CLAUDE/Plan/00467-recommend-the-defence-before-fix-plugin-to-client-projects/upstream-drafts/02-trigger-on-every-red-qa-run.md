# Draft: the skill description triggers on every red QA run, including one where a detector already fired

**Target**: `Defence-Before-Fix/claude-plugin`
**Status**: draft, not filed. This is a judgement from the description text. It has not yet been
observed live: the headless probe could not log in (see EVALUATION.md). Before filing, run one
logged-in session and record whether the skill fires on prompts A and C below.

## Title

`dbf` auto-triggers on "a failing check or a red QA run", which includes failures where the
project's detector has already caught the instance

## Summary

The skill's description (`skills/dbf/SKILL.md` line 3) says to use it whenever the user "asks
you to fix a bug, a defect, a failing check or a red QA run in a project".

A red QA run usually means one of two things:

1. **A detector fired.** A lint rule, type check or bespoke checker found an instance. The
   defence already exists and has just done its job. Running the full method from here means
   attributing a class, writing a new rule, dispatching two agents and running a sweep. That
   duplicates a defence the project has, for what is often a formatting or typing nit.
2. **A test or runtime check failed.** No detector saw the defect. This is where the method
   applies.

The description does not separate the two. In a project whose agents are routinely told to
"fix the red QA run" (formatters, type checkers, linters on every edit), the skill can fire on
every lint failure.

## Reproduction

1. Make a small Python project: `app.py` with `GREETING = 'hello'` and
   `def average(v): return sum(v) / len(v)`, and a test asserting `average([]) == 0`.
2. Enable the plugin, or start with `claude --plugin-dir <checkout>`.
3. Prompt A: "`python3 -m pytest` is red: test_empty fails with ZeroDivisionError. Fix the bug."
   Expected: the skill fires, correctly.
4. Prompt C: "The QA run is red: the lint step reports app.py line 1 uses a single-quoted string
   where the project style requires double quotes. Fix it." Expected: the skill stays quiet,
   because the style rule is the detector and it fired. Read against the description, it should
   fire.
5. Prompt B, the control: "Add a one-line docstring to greet." Expected: quiet.

## Suggested direction

- Narrow the trigger to defects that no detector caught: a failing test, a runtime failure, a
  bug report or a review finding. Or keep the trigger and make the first action of step 1 "Did
  the failure come from a detector the project runs? If so, the defence exists. Fix the
  instance, and consider only whether the rule should be wider."
- A text search of SPEC 1.0.1 finds no clause on a defect that an existing detector caught. If
  the method means such a defect to be out of scope, or handled differently, a sentence in the
  specification would let the skill's description cite it.
