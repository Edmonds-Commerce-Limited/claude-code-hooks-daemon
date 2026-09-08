# The handler option-injection contract, and what it can clobber

Supporting document for Plan 00353. This records the contract as it actually
is, the audit that bounded the blast radius, and why the fix landed in the
handler rather than the registry.

## The contract

`HandlerRegistry.register_all` runs two passes over every handler module. In
the second pass it does exactly this, per handler:

1. `instance = attr()` — construct with **no arguments**. The comment above it
   states the assumption outright: "Handler subclasses override `__init__` with
   no args."
2. `instance.priority = resolve_priority(...)`.
3. For each key in the handler's merged options (its own, plus a parent's when
   `shares_options_with` is set):
   `setattr(instance, f"_{option_key}", option_value)`.
4. Further cross-cutting injections by the same mechanism —
   `_project_languages`, `_project_exclude_paths`, `_project_layout`,
   `_project_registry`, and the plan-workflow attributes for planning-tagged
   handlers.

So the contract a handler must code against is:

> **An option named `X` in YAML arrives as `self._X`, holding the value PyYAML
> parsed, verbatim. It arrives AFTER `__init__` has finished, and it overwrites
> whatever `__init__` left there.**

Two properties follow, and both are load-bearing:

- A constructor's `options` parameter is **dead in production**. Nothing calls
  it with arguments. Anything read from it is only ever exercised by tests.
- A constructor that initialises `self._X` to a **transformed** value — a
  compiled regex, a `Path`, a `set`, an object — is writing into an address the
  registry is about to overwrite with a raw value, if `X` is ever a config key.
  The transformed type survives only while nobody configures the option.

`pipe_blocker` violated both at once, which is why the failure was total rather
than partial: `__init__` compiled `extra_whitelist` into `re.Pattern` objects
from an `options` dict it never received, and the registry then wrote the raw
`list[str]` over the (empty) result. `_matches_whitelist` called
`pattern.search(...)` on a `str`.

Note the near-miss sitting next to it. `_extra_blacklist` was initialised by
the same dead `options.get(...)` call — but it stored the value **verbatim**
(`list(...)`) and its consumer used `re.search(pattern_str, ...)`, which takes a
string. Injection therefore happened to produce exactly the type the consumer
wanted. The option worked, by accident, for the same reason its sibling failed.

## The audit

`__init__` bodies of all 121 production handler modules were parsed with `ast`
and every `self._X = <expr>` assignment classified as a verbatim store or a
transformation (call, comprehension, f-string, or a container of those). Each
was then intersected with the option-key candidates for that handler, harvested
from the module's own `options.get("X")` calls, its `getattr(self, "_X", ...)`
reads and its `Configuration options:` docstring block, plus every key
appearing under an `options:` block in the repository's YAML.

Result:

| Finding                                                           | Count |
| ----------------------------------------------------------------- | ----- |
| Handler modules scanned                                           | 121   |
| Constructors reading their `options` argument                     | 1     |
| **Transformed attributes whose name is a live config key**        | **1** |
| Transformed attributes whose name is not (currently) a config key | 97    |

The single live finding is `PipeBlockerHandler._extra_whitelist`. Nothing else
in the repository is exposed today.

The 97 are not a defect. They are ordinary constructor state —
`_rules_by_id`, `_formatter`, precompiled internal patterns — that merely
shares the shape that would become dangerous *if* a config key were later
introduced with a matching name. Rewriting them would be churn. What the plan
adds instead is the invariant that catches the reintroduction: **no production
handler `__init__` may read its `options` argument**. That is precise, has
exactly zero current violations after the fix, and forbids the mechanism by
which a transformed attribute acquires a config-key name in the first place.

`GhIssueCommentsHandler` and `GhPrCommentsHandler` also declare an `options`
parameter but never read it. The invariant permits that (the parameter is
inert), and removing the vestigial parameters is not worth a behaviour change.

## Why not fix the registry

The instinct is that the registry contract is the broken thing, since it is
the setattr loop that does the damage. The audit says otherwise: 120 of 121
modules honour the contract without difficulty, and the contract itself is
coherent and documented above. One handler implemented a second contract that
the registry has never called.

The registry-side fix also cannot be written. To "skip options the constructor
already consumed", the registry would have to know which **keys** a constructor
reads. Handler options are free-form — there is no per-handler option schema
anywhere in the codebase — and a signature discloses only that a `dict` is
accepted. The one implementable approximation, "pass the merged options to any
constructor that takes them and skip the loop for that handler", trades a bug
for a worse one: the handler would then also swallow `workspace_root`,
`exclude_paths`, `_project_layout` and every future cross-cutting injection it
does not know about, and those would silently stop arriving.

## The precedent the fix follows

`sensitive_content.py` already solves this correctly for its own regex-valued
option. It stores `public_patterns` raw, and compiles through a module-level
cache keyed on the source string, with an uncompilable pattern cached as a
documented no-match so a broken client config is not re-attempted per event.
Plan 00353 applies the same idiom to `pipe_blocker`'s two `extra_*` options,
which also removes the WET per-call `re.search(pattern_str, ...)` loop in
`_matches_blacklist`.
