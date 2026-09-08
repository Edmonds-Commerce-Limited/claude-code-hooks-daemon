# Budget-exhaustion detector: delivered vs. quoted (Tasks 1.4 / F2 and 4.5)

Supporting document for `PLAN.md` Tasks 1.4 (F2) and 4.5. Both findings are
the same self-reference gap in
`src/claude_code_hooks_daemon/handlers/post_tool_use/budget_exhaustion_detector.py`:
the handler's guards against firing on its own output key on a small set of
literal strings (the handler's module/class name, the ledger's filename), and
a ledger line, a `jq`-reformatted ledger dump, or a quotation that never
happens to spell one of those strings sails straight past them.

## The question the owner asked before code

> How does the detector distinguish a budget message the harness is
> DELIVERING to this agent now from one that merely APPEARS as text in
> something the agent read?

That is a question about **where the text sits in the hook payload and how it
got there**, not about what words it contains. A keyword list is a proxy for
that distinction; every incident the v3.60.0 gate hit is a case where the
proxy and the real thing came apart.

## What actually carries a delivered message vs. quoted content

`budget_exhaustion_detector` is `PostToolUse`-only (confirmed by its base
class, `PostToolUseHandlerBase`) and reads exactly one field for matching:
`hook_input["tool_response"]`. Nothing about `tool_input` is scanned for
content today — only `tool_input["command"]` is inspected, and only to check
it against the same literal marker list. That already narrows the question to
"which `tool_response` shapes are genuinely tool-delivered, and which are
just bytes some other process produced or reproduced".

Walking every false-fire in Task 1.4/4.5 against the actual field it arrived
in:

| Case                                                 | Field                         | What's really there                                                                                                                                                                                      |
| ---------------------------------------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WebSearch budget refusal (genuine, must keep firing) | `tool_response` (WebSearch)   | Text templated by Anthropic's own WebSearch tool integration for *this* call. Field-confirmed in `BUDGETS.md`.                                                                                           |
| `cat untracked/*.jsonl`                              | `tool_response.stdout` (Bash) | The ledger file's own bytes, unmodified, printed verbatim by a pure file-dump command.                                                                                                                   |
| `jq . untracked/budget*.jsonl`                       | `tool_response.stdout` (Bash) | The same bytes, *reformatted* (pretty-printed) but structurally the same ledger record.                                                                                                                  |
| `tail -n 20 "$LEDGER"`                               | `tool_response.stdout` (Bash) | The last N lines of the same file.                                                                                                                                                                       |
| `grep ... playbook.md` (Test 187 fixture quotation)  | `tool_response.stdout` (Bash) | A line of a *generated report file*, itself derived from this handler's own `get_acceptance_tests()` fixture string — grep neither creates nor budget-checks anything, it selects lines already on disk. |
| Sub-agent report quoting the Test 187 fixture        | `tool_response` (Task/Agent)  | The dispatched sub-agent's own final assistant message — prose composed by an LLM describing what it verified, not a field the Task/Agent tool integration itself populates from a live budget check.    |

Two structural properties fall out of that table, and both are properties of
**how the field got its content**, not of what the content says:

1. **Bash's `stdout`/`stderr` is not tool-native output — it is whatever the
   *command* produced**, and a command can either (a) invoke something live
   (`curl`, `python`, an MCP client, anything that can independently discover
   a real quota problem) or (b) merely **reproduce bytes that already exist
   on disk** (`cat`, `head`, `tail`, `grep`, `jq`, `awk`, `sed`, and the rest
   of the read/filter/reformat family). Only (b) is quoting. The dividing
   line is the **shape of the command** — its pipeline of leading verbs —
   not which file it happens to be pointed at. Keying on the verb instead of
   the filename is what makes this generalise past `budget-exhaustion-events.jsonl`
   to any file (a playbook, a copy of the ledger under another name, this
   handler's own source) without listing any of them.

2. **`Task`/`Agent` tool_response is never tool-native.** Every other
   default-excluded tool (`Read`, `Grep`, `Glob`, `Edit`, `Write`,
   `NotebookEdit`) is excluded because its `tool_response` is *file content
   the model already had*, not a live signal. A dispatched sub-agent's final
   message is the same category one level up: it is prose an LLM composed,
   never a field the Task/Agent tool machinery itself populates from a
   budget check. Critically, this costs no detection: if a sub-agent's *own*
   work genuinely hits a budget (e.g. it calls WebSearch and gets refused),
   that fires directly in the sub-agent's own session, at the WebSearch
   `PostToolUse` event, which is a completely independent hook invocation —
   hooks run per-session, and a dispatched sub-agent is its own session. The
   orchestrator's `Task` `PostToolUse` event, receiving the wrapped-up final
   report, is a strictly later, redundant, LLM-mediated restatement of
   whatever already fired (or didn't). Excluding it removes a
   false-fire-prone surface and loses no genuine signal.

Both properties are checked by **inspecting the structure of where the text
came from** (a command's verb shape; a tool's response-authorship model), so
neither is a string that has to be kept in sync with a growing catalogue of
filenames or handler spellings. New quoting sites — a different ledger copy,
a renamed playbook, a differently-worded sub-agent report — are covered
automatically because the rule is about the *shape* of the source, not its
name.

### The ledger's own JSON shape is a third structural signal (F2)

The ledger (`budget-exhaustion-events.jsonl`) is JSON Lines with a fixed,
small key set: `timestamp`, `session_id`, `tool_name`, `matched_fragment`. A
genuine harness-delivered budget message is natural-language prose from a
tool integration — it is never a JSON object carrying exactly this
handler's own record schema, because nothing outside this module ever
produces that shape. So before pattern-matching runs, the detector now scans
`tool_response` text for any brace-balanced JSON object whose keys are a
superset of that schema and removes it from consideration. This is a
*structural* recognition (parse the text, check the key set), not a keyword
check, and it is why it survives `jq .`'s pretty-printing: `jq` reformats a
JSONL line onto several lines, which defeats a literal-substring or
per-line-`json.loads` check but not a brace-balanced object scan across the
whole string.

## What was rejected, and why

- **Won't-fix.** Put to the owner and rejected: advisory-only noise still
  spends a real user-facing banner on a non-event and trains the reader to
  discount the next one, and the brief's "must never self-trigger on its own
  ledger" requirement is a MUST, not a nice-to-have.
- **Smuggle a marker into the Test 187 fixture string so the gate's own
  quotations self-exclude.** Put to the owner and rejected. It fixes the
  symptom at exactly one known quotation site (this handler's own acceptance
  fixture) while leaving every *other* quotation of a budget message —
  documentation, a bug report, a transcript excerpt, a different fixture —
  still false-firing. It is a workaround, not a fix, and it actively makes
  the underlying bug harder to see because the one reproduction the team
  already has stops reproducing it.
- **Grow `_SELF_REFERENTIAL_*_MARKERS` with more literal strings** (glob
  patterns for ledger filenames, additional handler-name spellings, etc.).
  This is the shape the owner explicitly ruled out ("not a keyword blocklist
  grown one string at a time"). It also cannot converge: Task 1.4's own
  three reproduction commands (`cat untracked/*.jsonl`, `jq . untracked/budget*.jsonl`,
  `tail -n 20 "$LEDGER"`) were chosen specifically because none of them
  spells the filename, so no finite list of filename/handler-name strings
  closes the gap — only a rule that stops caring about the filename does.
- **Exclude `Bash` from matching entirely.** Rejected: the handler's own
  test suite (`TestGenericBudgetShapes`, `TestNeverBlocks`,
  `TestOccurrenceLedger`) treats a Bash `tool_response` as a genuine
  detection surface (e.g. a live `curl` hitting a real quota), and
  `BUDGETS.md` explicitly designs the generic pattern family to catch
  "any future budget message... without a new handler per budget" — which
  includes budgets surfaced through an arbitrary CLI tool invoked via Bash.
  Blanket-excluding Bash would satisfy "never self-trigger" by also
  satisfying "never detect anything genuine via Bash", which the brief rules
  out as weakening. The command-verb-shape check keeps Bash eligible for
  everything except pure content-reproduction commands.
- **Parse ledger lines with one `json.loads` per line.** Considered as the
  whole fix for F2 and rejected as insufficient (kept only as one half of the
  structural check): `jq .` pretty-prints a record across several lines, so a
  strict per-line parse silently stops working on exactly the second of
  Task 1.4's three reproduction commands. The brace-balanced object scan
  (above) is what actually survives reformatting; belt-and-braces below adds
  the trivial single-line case back for a command whose command-verb-shape
  scan is somehow bypassed (e.g. a Bash one-liner combining a fetch and a
  ledger read where only PART of the pipeline is a genuine live call).
- **Literal `"matched_fragment"` marker as the whole fix (the plan's original
  suggestion).** Kept as a cheap, zero-risk *addition* to
  `_SELF_REFERENTIAL_RESPONSE_MARKERS` — a genuine harness message will never
  contain that exact key name as a bare substring either — but not relied on
  alone, because a marker is still a keyword and the JSON-shape scan already
  covers every case it would (and survives reformatting, which the bare
  string would not if `jq` inserted a line break or indentation between
  `"matched_fragment"` and its value... it wouldn't in practice, but the
  shape scan does not depend on that never happening).

## What changed

1. `_DEFAULT_EXCLUDED_TOOLS` gains `Task`/`Agent` (via the existing
   `SUBAGENT_DISPATCH_TOOL_NAMES` constant — single source of truth with
   `dispatch_declaration`/`agent_isolation_advisor`, which already use it for
   the same two tool names), for the reasons in property 2 above.
2. A new, closed, justified set of **content-passthrough verbs**
   (`cat`, `head`, `tail`, `less`, `more`, `grep`/`egrep`/`fgrep`/`rg`, `jq`,
   `awk`, `sed`, `strings`, `od`, `xxd`, `hexdump`, `wc`, `nl`, `cut`, `tac`)
   — utilities whose entire function is to reproduce or losslessly
   filter/reformat bytes from a named source, never to invoke a live
   service or generate new content. A Bash command is classified as
   content-passthrough when *every* pipeline stage's leading verb is in this
   set (segmented with the existing `shell_segmentation.split_unquoted`, the
   project's one canonical command-segmentation utility — Plan 00200/00222).
   `curl | jq .` is correctly NOT passthrough (curl is not in the set), so a
   live fetch piped through a formatter stays eligible for detection.
   Matching this classification excludes the response from matching, the
   same way `Read`/`Grep`/`Glob` responses already are.
3. A brace-balanced JSON-object scan of `tool_response` text strips any span
   that parses as a dict carrying the ledger's own record key set
   (`timestamp`, `session_id`, `tool_name`, `matched_fragment` — now declared
   once as `_LEDGER_RECORD_KEYS` and reused by both the writer and this
   recognizer) before pattern matching runs.
4. `"matched_fragment"` is added to `_SELF_REFERENTIAL_RESPONSE_MARKERS` as
   the belt-and-braces the plan asked for — redundant with (3) for every
   case tested, kept anyway because it costs nothing and a genuine harness
   message will never contain that exact key name.
5. The existing literal `_SELF_REFERENTIAL_COMMAND_MARKERS` /
   `_SELF_REFERENTIAL_RESPONSE_MARKERS` checks are UNCHANGED and still run —
   they still catch the one shape none of the above covers: a *generated
   report* whose producing command is not a content-passthrough verb (e.g.
   `python scripts/dump_playbook.py 190`) but whose output names this
   handler by class or module. The new checks are additive, not a
   replacement.

None of the above weakens the genuine cases: the WebSearch fixture and the
generic Bash "budget exhausted"/"quota exceeded" shapes used throughout the
existing test suite invoke no content-passthrough verb and carry no ledger
JSON shape, so they are untouched.
