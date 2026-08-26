# Phase 1 design: linting Ansible YAML on write

Decisions for Tasks 1.1 and 1.2, taken against the code rather than from the
report's sketch. The report is right that the gap exists; two of its
suggestions do not survive contact with what `lint_on_edit` actually does.

## 1. The gap, confirmed

`strategies/lint/` holds nine strategies — Shell, Python, Go, Rust, Ruby, PHP,
Dart, Kotlin, Swift. There is no YAML strategy and no YAML handling anywhere
else; `validate_eslint_on_write` covers `.ts`/`.tsx` only. So a project whose
primary artefact is Ansible playbooks gets every language linted on write
**except the one it is written in**.

## 2. Why an extension match is not enough, and where the discriminator goes

`LintStrategyRegistry.get_strategy` maps a file to a strategy by **extension
suffix alone**. Registering a strategy on `.yml`/`.yaml` would therefore claim
every YAML file in the repository — GitHub workflows, `hooks-daemon.yaml`,
inventories, `docker-compose.yml` — which the plan's Non-Goals forbid, and
which would produce exactly the noise that gets a handler disabled.

`skip_paths` cannot express the constraint: it is a substring **blacklist**,
and what is needed here is a positive test.

**Decision: a second, optional Protocol — not a change to `LintStrategy`.**

```python
@runtime_checkable
class NarrowsByPath(Protocol):
    def handles_file(self, file_path: str) -> bool: ...
```

The registry consults it when a strategy implements it, and treats every other
strategy exactly as it does today. Three reasons:

- **Interface Segregation.** Eight strategies have no use for the method, and
  adding it to `LintStrategy` would make all eight carry a `return True` stub.
- **It would break the existing suite.** `LintStrategy` is `runtime_checkable`,
  and `runtime_checkable` `isinstance` checks test member PRESENCE — there are
  **13** `isinstance(strategy, LintStrategy)` assertions across the strategy
  tests, and every one would start failing for a strategy that had not been
  given the stub.
- **It is already the house idiom.** `core/claude_md_injector.py` declares
  `HasClaudeMd` as a `runtime_checkable` capability protocol for precisely this
  "some objects can also do X" shape.

## 3. The discriminator, and the trap in the obvious version

The report proposes a path allowlist: `playbooks/`, `tasks/`, `roles/`,
`play-*.yml`, `playbook-*.yml`. That is a reasonable start and it is not
sufficient, for two independent reasons.

**It misses `site.yml`.** A playbook at the repository root — `site.yml` is
*the* canonical Ansible entry point — matches none of those patterns. A rule
that skips the most conventional file in the ecosystem is not worth shipping.

**Content sniffing alone is worse, and the reason is the motivating
incident itself.** The obvious content test is "parse it and check the shape":
an Ansible playbook is a top-level LIST whose mappings carry `hosts:`, while a
workflow, a daemon config and an inventory are all top-level MAPPINGS. That
discriminates cleanly — and it **cannot see the very file this feature
exists to catch**, because the incident was a file that FAILED TO PARSE. A
discriminator that requires a successful parse skips every broken playbook and
lints only the healthy ones.

**Decision: path OR text-sniff, with parse used only as confirmation, never as
a gate.**

1. **Hard exclusions first**, by path: `.github/workflows/`, `.gitlab-ci.yml`,
   `docker-compose*.yml`, `hooks-daemon.yaml`, `group_vars/`, `host_vars/`,
   `inventory`/`hosts.yml`.
2. **Vault files are never read or linted** — content beginning
   `$ANSIBLE_VAULT`. They are encrypted; linting one reports a failure about
   ciphertext.
3. **Accept on EITHER signal**: a playbook-shaped path (the report's list,
   plus a root `site.yml`), OR a cheap textual sniff that survives a broken
   file — a line matching `^\s*-\s+(hosts|name):` or a top-level `tasks:` /
   `roles:` / `handlers:` key.

The text sniff is deliberately crude. Its job is to keep working on the exact
input a parser rejects.

## 4. Working directory: reuse what Go already uses

The report warns that `ansible.cfg`, `.ansible-lint` and vendored collections
resolve relative to the project directory, so running from the wrong one makes
the linter fail for the wrong reason — worse than not running it.

**That machinery already exists and is already tested.** `lint_on_edit` has
`_MODULE_ROOT_MARKERS`, mapping a language to a marker file; `_find_module_root`
walks up from the file to the nearest directory containing it, and the result
becomes the subprocess `cwd`. Go maps to `go.mod`.

**Decision: add `"Ansible": "ansible.cfg"` to that map.** No new mechanism.

Known limitation, recorded rather than solved: the map holds ONE marker per
language, so a project with `.ansible-lint` but no `ansible.cfg` resolves no
root and runs from the daemon's cwd. `--syntax-check` on an absolute path still
works there; only role and collection resolution degrades. Widening the map to
a tuple of markers touches Go's entry and its tests for a case nobody has
reported, so it waits for a project that actually has that layout.

## 5. Tiering

Mirrors the existing cheap-syntax-then-deeper-linter split:

| Tier     | Command                                  | Why                                                                                |
| -------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| default  | `ansible-playbook --syntax-check {file}` | Catches the motivating load-time `split_args` failure, and is the cheap half       |
| extended | `ansible-lint {file}`                    | Catches `jinja[invalid]` and the rest; slow enough that it must not be the default |

`lint_on_edit`'s existing missing-linter leniency applies unchanged: a project
without `ansible-lint` installed gets an advisory, never a denial. That
leniency is this handler's, and is NOT shared by
`validate_eslint_on_write` — worth stating because the two are easy to conflate.

## 6. What this does not do

`--syntax-check` takes a **playbook**. A bare task file under `tasks/` — a
top-level list of tasks with no `hosts:` — is not one, and `--syntax-check`
will refuse it. Those files are covered at the `extended` tier by
`ansible-lint`, which does accept them, and are silently passed at the default
tier rather than reported as a failure the author cannot act on.
