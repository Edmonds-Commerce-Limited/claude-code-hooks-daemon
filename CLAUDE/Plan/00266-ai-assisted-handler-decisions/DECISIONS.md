# Trade-off analysis: should this daemon grow AI-assisted handlers, and how

## 0. Concrete evidence, not hypotheticals

Two real false positives happened in the course of writing this very plan —
both from handlers currently active in this repository, both on messages/
comments produced in this session. They are the strongest evidence in this
document, because they are not constructed examples.

### Example A: `nitpick.hedging_language` flagging honest, resolved uncertainty

While working this plan, an assistant message used "I suspect" and "may well
be" — and the `hedging_language` nitpick handler fired on it. But the same
message *also* said, explicitly, in the same breath: that the claim would
not be guessed at, that verifying it was the next step's first and
highest-priority question, and exactly what would settle it (asking the
`claude-code-guide` agent). The handler's own `get_claude_md()` guidance
states outright: *"Honest uncertainty is fine — say it plainly, and say what
would settle it."* This message did precisely that — and was flagged anyway.

The regex can see the hedge word. It cannot see that the very next clause
named the resolution path. **This is not a case of the phrase list being too
broad** — tuning it would not fix this, because the distinguishing feature
is not a phrase, it is whether the surrounding text commits to a
verification. That is meaning, not shape, which is the whole argument for
AI assistance on this specific handler.

### Example B: `qa_suppression` blocking a comment that argued *against* a suppression

Separately in this session, a code comment explained *why* a type-suppression
directive was **not** being used — and named the directive by name as part
of that explanation. `qa_suppression` blocked the write, reporting "Found 1
suppression comment(s)." The comment contained no suppression; it argued
against one. Rewording the comment to avoid spelling the directive out let
the write through — **the guard was satisfied by making the prose worse**,
which is the tell that the check is matching the wrong thing: literal
presence of a string, not whether the string is being *used* or *mentioned*.

**This one is sharper than a plain bug, because the project has already
decided, in writing, to accept this exact failure mode.**
`/workspace/CLAUDE.md`'s "Blocking Handler False Positives in Commit
Messages" section states the false-positive matching is *intentional*,
because the acceptance-test strategy depends on it: blocking handlers are
verified by embedding the literal dangerous string inside a harmless command
(`echo "git reset --hard"`) and asserting the handler still fires. **Any
proposal to soften this class of false positive must not break that testing
strategy** — see §3c below for a design that satisfies both.

### Documented evidence already in the tree

`comment_changelog`'s own guidance names four signals it *demoted* from
blocking to advisory after a whole-repo self-scan found each firing on
legitimate code: a version-transition arrow (`1.2 -> 1.3`), a changelog verb
naming a version, multiple versioned entries in one comment, and
retrospective phrasing (`used to`, `no longer`). The stated reason in each
case is the same shape as Examples A and B — a version-processing utility
legitimately citing multiple versions in its own docstring, "removed in vX.Y"
describing an *external* tool's own deprecation rather than this project's.
**The handler's answer to "the pattern can't tell rationale from changelog"
was to give up on catching those four shapes at all, rather than understand
the text.** That is the cost of the current approach, paid in coverage, and
it is the same root cause as Examples A and B: pattern-matching cannot
distinguish mention from use, or a legitimate exception from the thing being
guarded against.

Three independent handlers (`hedging_language`, `qa_suppression`,
`comment_changelog`), one root cause. That convergence — not any single
example — is the strongest argument in this plan for building something.

## 1. The latency problem is the crux — worked through, not hand-waved

This daemon's entire reason for existing (`CLAUDE.md`'s opening paragraph) is
that it replaced a ~198ms cold Python start with a ~45ms warm socket round
trip, of which daemon-side dispatch is ~1.8ms. A synchronous LLM call is
**1-3 seconds** even for a fast/cheap model — three orders of magnitude
slower than the property this project was built to deliver, and roughly
40-70x slower than the "slow" baseline (198ms) it replaced the *cold-start*
path to avoid.

### Which event types can absorb that, and which cannot

The daemon's dispatch call (`self.controller.dispatch`) runs inside
`asyncio`'s default thread-pool executor (confirmed in
`src/claude_code_hooks_daemon/daemon/server.py:1085` —
`await loop.run_in_executor(None, self.controller.dispatch, hook_input)`),
so a slow handler does **not** freeze the daemon's event loop for other
concurrent sessions sharing the same daemon (self-install mode + parallel
sessions share one daemon per `CLAUDE.md`). It only blocks the *one* client
connection waiting on that response — but that is still exactly the
connection whose tool call, turn, or session start is waiting.

| Event                                      | Gates what?                                                                                        | Tolerates 1-3s?                                                                                                            | Why                                                                                                                                                                     |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PreToolUse`                               | The tool call itself — nothing runs until this returns                                             | **No**                                                                                                                     | Every guarded tool call (which is most of them, in this project) would feel broken. This is precisely the regression the daemon's own README opening exists to prevent. |
| `PermissionRequest`                        | A permission prompt                                                                                | **No**, same reason                                                                                                        |                                                                                                                                                                         |
| `PostToolUse`                              | Nothing execution-wise — the tool already ran. Only delays *when the agent sees advisory feedback* | **Marginal** — acceptable for advisory-only, infrequent judgement, not for anything the agent needs before its next action | The nitpick pseudo-event already fires here (`pre_tool_use:1/5` sampling)                                                                                               |
| `Stop`                                     | End-of-turn — the user is already waiting for the turn to end regardless                           | **Marginal, not free — see §1b**                                                                                           | nitpick also fires here, `stop:1/1` — every turn                                                                                                                        |
| `SessionStart`                             | Once per session, already does meaningfully slow I/O (git fetch, version checks)                   | **Yes**                                                                                                                    | Already tolerates seconds of latency (network calls) as a matter of course                                                                                              |
| `PreCompact`, `SessionEnd`, `Notification` | Rare, not in a user-facing critical path                                                           | **Yes**                                                                                                                    |                                                                                                                                                                         |
| `UserPromptSubmit`                         | Delays the agent starting to work on the prompt the user just sent                                 | **No, or only barely** — the user just hit enter and expects the agent to start responding                                 |                                                                                                                                                                         |

**Conclusion: latency rules out `PreToolUse`/`PermissionRequest`/
`UserPromptSubmit` for anything synchronous, and makes `PostToolUse` viable
only when sampled/rate-limited (as nitpick already is) rather than run on
every event.** `Stop` and `SessionStart` are the safe synchronous homes —
but "safe" needs testing, not assuming; see §1b.

### 1b. Testing the "nitpick is near-free" claim, rather than assuming it

It is tempting to conclude nitpick is free because it is advisory: nothing
it does can wrongly block a tool call, and a wrong finding costs only a
stray, low-stakes advisory line. **That part is true and confirmed** — both
nitpick handlers construct `HookResult(decision=Decision.ALLOW, ...)`
unconditionally, so there is no wrong-block risk to test for.

But "advisory" and "the user perceives zero added latency" are not the same
claim, and the second one does not survive testing. `PseudoEventDispatcher`
fires the nitpick chain **inline**, as part of the real `Stop` event's own
dispatch (`_fire` runs `registered.chain.execute(enriched)` synchronously
within that request) — it is not currently a fire-and-forget background
task. If a nitpick handler makes a synchronous model call inside that chain,
the `Stop` response the user is waiting for does not return until the model
call finishes. The tool-call gating risk is genuinely zero (nothing runs on
`Stop` returning); the **perceived-latency risk is not zero** — the user
would experience a 1-3 second pause at the end of every turn, which is a
real, noticeable regression even though nothing was technically "blocked."

**What would actually deliver the near-zero-perceived-cost the intuition is
reaching for is the deferred design from §1's alternative below, applied
specifically here**: the `Stop` handler kicks off the model call
out-of-band and returns immediately with whatever it already has (nothing,
the first time); the finding surfaces on a **later** event — the *next*
`Stop`, or the next nitpick-eligible `PreToolUse` — once it's ready. This
costs one turn of lag per finding and does require the background-task
infrastructure §1's "deferred/async alternative" already names as new
work, but it is what actually cashes out the "nitpick is cheap" intuition
rather than merely asserting it. A same-turn synchronous call on `Stop` is
not that; it's a smaller, more tolerable latency hit than `PreToolUse`, not
a free one.

### The deferred/async alternative

A handler can return immediately (ALLOW, no opinion) and kick off the model
call out-of-band, surfacing the result on a **later** event — e.g. a
`PostToolUse` handler queues a judgement, and the *next* `PreToolUse` or
`Stop` picks up a cached verdict if one is ready, otherwise says nothing.
This trades immediacy for zero added latency on the gating path, at the cost
of: the finding always arrives one event late (never blocks the thing it
judged, by construction — which may be exactly the right constraint,
see §3); and it requires genuinely new daemon infrastructure (a background
task/worker, a results cache keyed by session+content, cleanup policy) that
does not exist today. This is a real option, not merely a caveat — several
of the ranked ideas in `IDEAS.md` are structured this way, and §1b concludes
it is the option that actually delivers what "nitpick is nearly free"
intends to claim.

### The native-hook path has the identical latency problem

It is tempting to think "just use Claude Code's own `prompt`/`agent` hook
type and the latency problem becomes Anthropic's to solve." It does not:
`prompt` hooks default to a 30s timeout, `agent` hooks to 60s — Claude Code's
own docs are implicitly acknowledging these are *slow* operations, not
disputing it. A native `prompt` hook on `PreToolUse` blocks the tool call for
however long the model takes to answer, exactly like a daemon handler would.
The choice of mechanism (see `RESEARCH-claude-code-native-hooks.md`) does not
sidestep this section; it only changes who pays the implementation cost.

## 2. Determinism, testability and trust

This project's engineering culture is unusually strict: TDD mandatory, 95%
coverage minimum, `get_acceptance_tests()` producing a playbook of exact
expected decisions executed in a real Claude Code session before every
release, and a `HookResult`/`AdvisoryResult`/`BlockingResult`/`GatingResult`
type hierarchy (Plan 00265, in progress) that makes some classes of bug
*unwritable* rather than merely tested-for. An AI-judged handler challenges
essentially all of this at once:

- **A unit test asserting an exact decision from a model call is not really
  testing the handler** — it is testing whether the model, today, with
  today's weights, on this exact input, produces this exact output. That is
  brittle in a way this project's test suite has never had to tolerate.
  The honest answer is to **mock the model call in unit tests** (assert the
  handler correctly turns a given model response into a `HookResult`) and
  treat the model's actual judgement quality as a *product* question
  evaluated separately (a small eval set, reviewed periodically), not a QA
  gate that must stay green on every commit.
- **Acceptance tests currently assert exact `expected_decision` +
  `expected_message_patterns`.** An AI handler's wording will vary run to
  run even when its *decision* is stable. Acceptance tests for an AI handler
  would need to assert decision-class stability on a fixed small corpus of
  known-clear-cut inputs, not exact message text. Examples A and B in §0 are
  themselves good candidates for that corpus: a fixed regression case per
  handler, re-run whenever the model changes.
- **Does an AI handler ever get to DENY?** This is the sharpest question in
  the whole plan, and this codebase already has the right primitive for
  answering it conservatively: `AdvisoryResult` (`core/result_types.py`)
  literally cannot construct a DENY — the `decision` field's type is
  `Literal[Decision.ALLOW, Decision.CONTINUE]`, enforced both by mypy
  statically and by Pydantic's `validate_assignment` at runtime. **A first
  AI-driven handler should be pinned to `AdvisoryResult` by construction**,
  so a hallucinated "this should be denied" from the model is not a policy
  question to get right in every handler's code — it is impossible to
  express in the type the handler is required to return. This is a
  materially stronger guarantee than "we will remember not to let it deny
  things." Blocking on an LLM's say-so is a *later*, harder-earned
  capability, if ever — not a starting posture. (§3c's "confirm-the-positive"
  design gives a second, narrower way to let AI influence a *blocking*
  handler without ever letting the model itself originate a block — read
  the two together.)
- **Cost, rate limits, and offline operation.** Every existing handler
  works with zero external dependencies and zero marginal cost per
  invocation. An AI handler needs: a resolvable API credential (what happens
  with none configured — silent skip, loud warning, hard fail? — must be
  "fails open," per Core Standard 6's spirit adapted for external
  dependencies: a broken/unavailable model call must never block the user's
  actual work); a per-call cost that scales with usage (a `pre_tool_use:1/5`
  sampling rate like nitpick's, or coarser, is not just a latency mitigation
  but a cost-control one); and a firm rule that a model-call *error*
  (timeout, 429, network failure) degrades to ALLOW/no-opinion, never to a
  block or a crash — the daemon's own Core Standard 6 ("FAIL FAST... crash
  immediately") is written for *internal* logic bugs, and applying it
  naively to an *external service* failure would turn every Anthropic API
  hiccup into a blocked user. That tension needs an explicit, written
  exception for this one class of handler.

## 3. Where an AI judgement is least risky to introduce first

The `nitpick` pseudo-event (`src/claude_code_hooks_daemon/pseudo_events/nitpick.py`,
`core/pseudo_event.py`, `handlers/nitpick/*`) is architecturally the closest
existing thing to what an AI-assisted handler needs, and is the natural first
home:

- It already exists to judge **prose meaning** — `dismissive_language.py` and
  `hedging_language.py` scan assistant message text for regex phrase lists
  approximating a semantic judgement ("is this deflection or a legitimate
  scope note?"). That is exactly the shape of problem a regex is structurally
  bad at and a model is comparatively good at. Example A in §0 is a live
  instance of `hedging_language` failing this exact way.
  `dismissive_language.py`'s own `get_claude_md()` already documents a
  second such approximation failing in a known, principled way: *"A QUOTED
  phrase is a mention, not a deflection... quoting one never re-fires the
  advisory"* — the regex needed a bespoke carve-out (`blank_quoted_spans`) to
  avoid penalising an agent for *naming* the pattern it was told to avoid. A
  model would likely get this distinction for free, without a hand-written
  exemption for every such case the regex authors happen to think of.
- It is **advisory-only by construction today** — both nitpick handlers
  return `HookResult(decision=Decision.ALLOW, context=[...])`. Nothing about
  the pseudo-event mechanism currently lets a nitpick handler deny anything.
  (Note: this is by convention in the handler body today, not yet enforced
  at the type level the way `AdvisoryResult` enforces it elsewhere — pinning
  nitpick handlers to `AdvisoryResult`'s type would upgrade "advisory by
  choice" to "advisory by construction," closing that gap.)
- It is **already sampled/rate-limited by design** (`pre_tool_use:1/5`,
  `stop:1/1` in `.claude/hooks-daemon.yaml`), which is precisely the cost and
  latency control an AI judgement needs, already built and already dogfooded.
- Its trigger points (`PreToolUse` at 1-in-5 sampling, and `Stop` on every
  turn) are, per §1's table, in the least-bad latency band — but per §1b, a
  synchronous call on either still adds a perceptible pause; the deferred
  design is what actually makes this "cheap" rather than merely "cheaper
  than `PreToolUse`."

This is not a coincidence worth ignoring: **if this project builds exactly
one from-scratch AI judgement, the nitpick chain is where it costs the
least new infrastructure and inherits the most existing safety margin.**
But §3c below identifies a second, differently-shaped design — motivated
directly by Example B — that is arguably safer still for a *blocking*
handler, which nitpick's advisory handlers do not need to solve for.

## 3b. A third mechanism this codebase already uses, and why it's not always the answer

Everything above assumes the daemon (or Claude Code) makes an independent
model call. But this project already ships a cheaper pattern for getting AI
judgement applied, at **zero API cost and zero added latency**: a handler
that does not judge anything itself, but detects a *situation* and injects
advisory context telling the **current agent session** — which is already an
LLM, mid-turn — to go apply judgement itself. `idle_housekeeping_advisory`
is exactly this: on repeated idle ticks it suggests dispatching specialist
sub-agents that "run read-only audits and write shareable markdown report
files." `recovery_cron_advisor` and `agent_isolation_advisor` are the same
shape — the daemon notices a condition and hands the *agent* a judgement to
make, rather than making the judgement itself.

Call this **Mechanism C**, alongside native Claude Code `prompt`/`agent`
hooks (Mechanism A) and a daemon handler calling a model directly
(Mechanism B). It is the right fit whenever the judgement is a **self-audit
with no conflict of interest** — "is this documentation stale," "does this
plan's task list match reality" — because there is no reason not to let the
same session that can fix what it finds also be the one that finds it, and
it costs nothing beyond the tokens of a turn the user was going to pay for
anyway.

It is the **wrong** fit whenever the judgement needs to be independent of
the agent being judged. `nitpick`'s handlers exist specifically to catch the
*current* agent's own dismissive or hedging language — asking that same
agent to self-report "was I just being dismissive?" mid-task has an obvious
conflict of interest (the same pressure that produced the dismissive
phrasing in the first place is present when grading it). A regex is a weak
judge but an *disinterested* one; the value of upgrading it to Mechanism A
or B (an independent model call — see §5, both satisfy independence equally,
since neither is the same agent turn grading itself) is keeping that
disinterestedness while gaining semantic accuracy. Swapping it for
Mechanism C would gain accuracy but lose the one property regex had going
for it. Several ideas in `IDEAS.md` split cleanly along this line —
self-audit vs. self-policing — and that split, more than latency, is what
should decide their mechanism.

## 3c. Two shapes of AI filter: confirm-the-positive vs second-opinion

Example B (§0) suggests a design distinct from "replace the regex with a
model": leave the deterministic matcher exactly as it is — fast, testable,
and load-bearing for the acceptance-test strategy §0 describes — and use a
model only as a **second stage**, invoked only when the regex has already
matched, to answer one narrow question: "is this a genuine use of the
flagged pattern, or a mention of it?" If the model says "mention," the block
downgrades to allow (or to an advisory). If the model is unavailable, times
out, or errors, the handler falls back to **today's exact behaviour** — the
regex's own decision, unchanged. Call this **confirm-the-positive**.

This inverts §1's latency problem instead of merely mitigating it: the model
only ever runs on the rare event where the regex *already* matched (most
writes to most files never touch a suppression directive or a security
pattern at all), not on every event of that type. It also inverts the
determinism risk in §2: a model outage cannot make the handler behave worse
than it does today, only occasionally better (fewer false-positive blocks) —
there is no new failure mode where the daemon is down a protection it
previously had, because the fallback *is* the previously-shipped behaviour.

**Its structural weakness, stated plainly: confirm-the-positive can only
ever improve precision (fewer wrongful blocks), never recall (it cannot
catch what the regex missed in the first place).** That is the right trade
for handlers whose demonstrated failure mode *is* false positives —
`qa_suppression` (Example B), `comment_changelog` (the four demoted signals
in §0) — because in both cases the existing regex is already conservative
enough on the recall side that the project tolerates it, and the pain being
felt is precision. It is the **wrong** trade for `security_antipattern` and
`sensitive_content`, whose stated failure mode in `CLAUDE.md`'s own handler
guidance is the opposite — missed cases (SQL injection, obfuscated secrets),
not false alarms. Those two need what could be called a **second-opinion**
filter instead: a model that runs *independently* of the regex (not gated on
it matching first) and can only ever **add** an advisory flag, never
subtract a block and never issue one itself. `IDEAS.md` #9 is already shaped
this way; #8 is explicitly rejected regardless of filter shape, because the
event (every source-file write) is too hot for either design to run
unsampled, and a probabilistic recall improvement on a "ZERO TOLERANCE"
security surface is the wrong place to introduce a probabilistic judge at
all.

**Naming the asymmetry precisely: confirm-the-positive is safe to let
influence a *blocking* decision (it can only ever unblock, never newly
block); second-opinion must stay advisory-only forever (it can only ever
flag, never block), because letting a probabilistic "I found something"
become an autonomous block would recreate every risk §2 raises, on exactly
the surface (security) where this project is least willing to accept it.**

## 4. Does a daemon-side AI handler need to exist at all, given native hooks?

`RESEARCH-claude-code-native-hooks.md` confirms native `prompt`/`agent`
hooks are real, adoptable with no code to write, and — per that document's
follow-up research — **run in parallel with this daemon's own `command`
hook on the same event**, never as a replacement for it — see the
reconcile-is-additive-per-event footgun there. That changes the
question this plan has to answer. It is no longer "can we have AI-driven
hooks" — it is "given Claude Code already has them natively, does building
one inside this daemon earn its cost."

**Against building daemon-side** (i.e. just use native hooks):

- Already exists, maintained upstream, costs this project no code.
- Configuration is a few lines of JSON per event; no new Python, no new
  tests, no new dependency to keep working.
- Cannot introduce a new failure mode into a daemon whose own dispatch is
  ~1.8ms, because it never touches the daemon process at all.

**For building daemon-side:**

- **Native hooks cannot express confirm-the-positive (§3c) at all**, and
  this is the decisive argument, not a preference. A native `prompt`/`agent`
  hook only ever sees the raw hook input JSON (plus, for `agent`, whatever
  Read/Grep/Glob can find on disk) — it has no visibility into *this
  daemon's own regex's match*. To reproduce confirm-the-positive natively,
  the pattern logic would have to be duplicated inside the hook's prompt
  text (a second, untested, drifting copy of logic this project already
  unit-tests) or the model would have to run on **every** matching event
  unconditionally (reintroducing the full cost/latency §1 rules out, since
  there is no "only when our handler already flagged something" gate to
  hook into from outside the daemon). Either way, the one design this plan's
  own concrete evidence (§0) most directly motivates is not reachable via
  Mechanism A at a comparable cost.
- **`nitpick`'s dependency on incremental transcript state** (`NitpickState`'s
  per-session byte offset, `NitpickSetup`'s "new messages since last audit"
  slicing) has no native equivalent — a `prompt`/`agent` hook gets one
  event's JSON, not a maintained cursor into the session transcript. Building
  this outside the daemon means rebuilding that bookkeeping from scratch.
- **`agent` hooks have no Bash tool access** (confirmed —
  Read/Grep/Glob only), which rules them out for any judgement needing
  subprocess output (e.g. `git diff --cached` for a commit-message-coherence
  check, `IDEAS.md` #5) unless that output is already present in the hook's
  own JSON input.
- **Reproducibility**: `RESEARCH-...md` confirms the native hooks' default
  model is documented only as "a fast model," with no name, tier, or
  stability guarantee — a real risk for a project that pins exact decisions
  in acceptance tests. A daemon-side model choice is a line in this
  project's own code, changed deliberately and reviewed like anything else.
- **Everything native bypasses this project's entire apparatus** — no
  `Handler`/`HookResult`/priority chain, no config YAML, no
  `get_claude_md()`, no acceptance-test generation, no `verdict_log`, no
  QA gate. Anything expressed only in `settings.json`/`hooks.json` JSON is
  invisible to every guarantee this project has built, and collides with
  `hook_registration_checker`'s current "everything routes through the
  daemon wrapper" policy (§ in `RESEARCH-...md`) unless that policy is
  deliberately carved out.

**Recommendation: hybrid, decided per-idea by whether the judgement depends
on daemon-side state or a prior daemon-side match.** Confirm-the-positive
designs (built on this project's own regex matches) and anything needing
`NitpickSetup`'s transcript bookkeeping or subprocess output **must** be
daemon-side (Mechanism B) — native hooks cannot reach them at comparable
cost, full stop. A **standalone whole-event judgement that needs nothing
the daemon already computed** (e.g. `IDEAS.md` #3's "is this text a stable
instruction or a session-log sentence," which only needs the file content
already in `tool_input`) is native-hook-*eligible* — cheaper to prototype via
Mechanism A first, before ever writing daemon infrastructure for it, though
adopting it project-wide still has to resolve the `hook_registration_checker`
policy tension. `IDEAS.md`'s ranking table below maps every candidate into
one of these buckets explicitly, because "which mechanism" turned out to be
a per-idea question, not a project-wide one.

## 5. Mechanism recommendation, given §0-4

Two designs earn building, for different reasons, and neither is reachable
via native hooks at comparable cost (§4):

1. **`nitpick` semantic upgrade** (Mechanism B, deferred/async per §1b, `Stop`
   trigger), pinned to `AdvisoryResult`, fail-open on every external error.
   Motivated by Example A. Reuses the most existing infrastructure of
   anything in `IDEAS.md`.
2. **Confirm-the-positive filter for `qa_suppression`/`comment_changelog`**
   (Mechanism B, invoked only on an existing regex match, so cost is
   inherently sampled to "rare positive" rather than "every event" even
   though the base event is `PreToolUse` on every source write). Motivated
   by Example B. Structurally the safest way this plan found to let AI
   influence a *blocking* decision, because it can only ever remove a block,
   never add one.

Both keep the engineering discipline this project insists on (still a real
`Handler`, still unit-testable by mocking the model call, still shows up in
`verdict_log`/`generate-docs`). Native `prompt`/`agent` hooks remain the
right call for a genuinely standalone, one-off, project-specific judgement
that does not depend on daemon state (the `git tag`/`RELEASING.md` example
`ARCHITECTURE.md` already sketches, or `IDEAS.md` #3) — worth trying there
first, precisely because it costs nothing to try, before committing to
daemon infrastructure for it.

## 6. What would raise confidence further

Everything above is reasoned from source code and official docs, not
guessed. Follow-up research resolved two of the original open questions
(hook coexistence: confirmed hooks of different types run in parallel on the
same event; default model: confirmed undocumented beyond "a fast model," a
finding rather than a gap-fill) — but five remain genuinely unverifiable from
documentation alone and are named rather than papered over in
`RESEARCH-claude-code-native-hooks.md`'s "what still could not be settled"
section: minimum Claude Code version, per-event availability, permission-mode
interaction, cost/billing, and the exact cross-type decision-precedence rule.
None of these blocks the recommendation in §5, which does not depend on any
of them — but all five would matter before ever recommending the native-hook
path to a client project as a supported pattern.
