## 07:04 · action · —   — Delivered: 77 alerts to 18; three held by upstream pins; anyio option fix

Plan 00593 is delivered and archived. Open Dependabot alerts dropped from 77 to 18.

**Bumped (6 packages):** nltk, anyio, virtualenv, urllib3, cryptography, idna.

**Held (3 packages):** the remaining 18 alerts all belong to these. Each is pinned by the latest release of a dev tool, confirmed against PyPI metadata:

- filelock (13 alerts): `safety` 3.8.1 requires `filelock<4.0`.
- mcp (4 alerts): `semgrep` 1.184.0 requires `mcp==1.29.0`.
- opentelemetry-api (1 alert): `semgrep` 1.184.0 requires `opentelemetry-api~=1.37.0`.

They clear when `safety` or `semgrep` release with looser pins.

**CI incident:** the bump broke one test on main. anyio 4.16 registers a new pytest option, `--anyio-mode`, and the full-QA blocker's option-table rot detector caught it. The fix (`cc6ace282`) adds the option to `PYTEST_VALUE_OPTIONS`; it reproduced RED locally first.

The implementer's targeted QA had passed. The likely cause is that its worktree venv was not synced to the new lock. Future lock-bump briefs should require a venv sync check before QA.

**Daemon venv:** the main venv needed `hooks-daemon repair` after the lock change, because restart reuses the old venv.

PR #193 (nltk only) was closed by Dependabot.
