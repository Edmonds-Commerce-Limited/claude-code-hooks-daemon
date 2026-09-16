# Plan 00426: shipped plugins examples do not validate

**Status**: Complete
**Created**: 2026-09-16
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct
**GitHub Issue**: #44

## Overview

Three surfaces show a project how to configure plugins. Two of them cannot
load. Validated directly against `PluginsConfig` before this plan was filed:

| Shape                                       | Where                                                   | Result                                           |
| ------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------ |
| `type`/`class`/`events`                     | `.claude/hooks-daemon.yaml.example`                     | INVALID — `Input should be a valid dictionary`   |
| `paths` + `plugins[].path/handlers/enabled` | `docs/guides/CONFIGURATION.md`, `examples/basic_setup/` | INVALID — `plugins.0.event_type: Field required` |
| the same, plus `event_type`                 | this repo's own live `.claude/hooks-daemon.yaml`        | VALID                                            |

The issue reports the first as stale and proposes replacing it with the second.
That would swap one invalid example for another: `PluginConfig.event_type` is
required with no default, and it appears in neither documented example. The only
shape that validates is the one nobody wrote down.

A text correction alone would leave the same trap armed, because nothing checks
these examples — they drifted precisely because no test reads them. So the
durable half of this plan is a test that validates every shipped `plugins:`
example against the model that has to accept it.

Issue #44's second question — whether unknown keys in remote-docs provenance
frontmatter are a supported extension point — is an owner decision and is
recorded here rather than answered. See
[PROVENANCE-EXTRA-KEYS.md](PROVENANCE-EXTRA-KEYS.md).

## Goals

- Every `plugins:` example this project ships validates against `PluginsConfig`.
- A test enforces that, reading the shipped files themselves rather than a copy,
  so the next drift fails instead of shipping.
- The owner decision behind #44's second question is recorded with its evidence,
  so answering it needs no re-derivation.

## Non-Goals

- **Answering whether extra provenance keys are a contract.** That is product
  intent. This plan records the evidence and the options; the owner decides.
- **Changing `PluginConfig` itself.** `event_type` being required is the
  model's decision and is not in question here — the examples are wrong, not the
  model.
- **Auditing every other example block in the config docs.** This plan fixes the
  `plugins:` examples that #44 names and pins them. A wider sweep is its own
  work; if the pinning test proves cheap, extending it is a natural follow-up.

## Tasks

### Phase 1: pin the invariant

- [x] ✅ **Task 1.1**: RED — a test that extracts the `plugins:` block from each
  shipped surface (`.claude/hooks-daemon.yaml.example`,
  `examples/basic_setup/hooks-daemon.yaml`, `docs/guides/CONFIGURATION.md`) and
  validates it against `PluginsConfig`. It must fail now, naming each invalid
  file — that failure IS the reported defect.

  Read the files as shipped. A test carrying its own copy of the YAML would pass
  forever while the real examples rot, which is the failure mode that produced
  this issue.

### Phase 2: correct the examples

- [x] ✅ **Task 2.1**: Fix `.claude/hooks-daemon.yaml.example` — replace the
  `type`/`class`/`events` comment block with a shape that validates.

- [x] ✅ **Task 2.2**: Fix `docs/guides/CONFIGURATION.md` and
  `examples/basic_setup/hooks-daemon.yaml` — add the required `event_type` to
  each entry, and say in the surrounding prose that it is required, since its
  absence is what made both examples unloadable.

### Phase 3: the recorded decision

- [x] ✅ **Task 3.1**: Write [PROVENANCE-EXTRA-KEYS.md](PROVENANCE-EXTRA-KEYS.md)
  — the measured behaviour, why the `unchanged` case makes it more than
  cosmetic, and the options with their consequences. No recommendation dressed
  as a finding.

## Success Criteria

- [x] ✅ Every shipped `plugins:` example validates against `PluginsConfig`,
  proven by a test that failed first and reads the shipped files.

  `tests/integration/test_shipped_plugins_examples.py` reads the three shipped
  surfaces as files. It failed RED on **four** invalid blocks — one more than
  hand inspection found, because `docs/guides/CONFIGURATION.md` carries two.
  All four now validate. It also carries
  `test_the_shipped_surfaces_are_actually_found`, so a broken extractor cannot
  pass vacuously by finding nothing.

- [x] ✅ The test fails if any of those files drifts again — verified by
  breaking one on purpose, not assumed from the fact that it passes.

  The RED run IS that evidence: the four failures name the four files, and the
  same assertions pass only after each is corrected. A companion check in this
  work's other half was separately proven able to fail by reintroducing its
  defect (`assert 1 == 0`) and restoring byte-identical to HEAD, because a test
  that has only ever passed has not been shown to be capable of failing.

- [x] ✅ Issue #44's second question is recorded with enough evidence that the
  owner can decide without re-running anything.

  [PROVENANCE-EXTRA-KEYS.md](PROVENANCE-EXTRA-KEYS.md) holds the measured
  table, why the `unchanged` case makes it more than cosmetic, and three
  options with their consequences — no recommendation dressed as a finding.
  Issue #44 stays OPEN under `agent-needs-human`.

- [x] ✅ Full QA green, read from the suite's own exit line.

  `QA_EXIT=0`, 35/35 passed, smoke_test 3/3; `plan_qa`, `docs_qa`,
  `sensitive_content`, `british_english` and `project_handlers` (192 passed)
  clean. CI run `35143755362` on the merge commit `fd414e5e`:
  `status=completed`, `conclusion=success` — read from the run, not from the
  watcher's exit code.

- [x] ✅ Every release-bound consequence is in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/`) before the status flips, or this criterion says
  explicitly that the plan has none.

  `CLAUDE/UPGRADES/UNRELEASED/release-notes/03-shipped-plugins-examples-now-validate.md`.
  No config change, no truth change and no upgrade task: the model was never
  altered, only the examples that had to satisfy it.

## Delivery & Milestones

- Filed from issue #44 after validating all three shapes against the model. The
  issue asked which of two schemas was real; the measured answer is neither.
