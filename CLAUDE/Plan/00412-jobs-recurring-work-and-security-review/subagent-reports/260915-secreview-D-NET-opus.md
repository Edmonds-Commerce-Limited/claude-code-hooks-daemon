# Security review — D-NET (new network egress, and what it does with the response)

**Check**: `D-NET` — "New network egress — any new fetch, and what it does with
the response." (`CLAUDE/Routine/00001-security-review-full/CHECKS.md:42`)

**Run**: Routine 00001, run 2026-001, FULL sweep. Reviewed the current tree at
`HEAD 5d59f7ff`, not a diff.

**Method note**: this was answerable. Every egress point below was read in
source. No network request was made. The one place I could not fully settle a
reachability question (N3's dependence on `agent-browser`'s own URL handling) is
marked as such rather than asserted.

**Findings**: 9 (2 high, 4 medium, 3 low). Confidence per finding below.

---

## Part 1 — The egress inventory

Every point in this repository that reaches the network, and the trust it
places in what comes back.

| #   | Where                                         | Mechanism                                              | Destination                                                    | What it does with the response                                                                             |
| --- | --------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| E1  | `remote_docs/fetchers.py:113`                 | `urllib.request.urlopen`                               | any https URL a caller names                                   | bytes written to disk as a vendored document, later read into agent context                                |
| E2  | `remote_docs/fetchers.py:209`                 | `subprocess.run([agent-browser, read, <url>, --json])` | any URL                                                        | JSON parsed, `data.content` written to disk as above                                                       |
| E3  | `install/relay_deploy.py:275`                 | `urllib.request.urlopen`                               | `github.com/.../releases/download/<tag>/...`                   | **an executable binary**, `chmod 0o755`, run as the hook relay                                             |
| E4  | `handlers/session_start/version_check.py:144` | `git ls-remote --tags` via `run_git`                   | hardcoded daemon repo                                          | a tag string, rendered into SessionStart context                                                           |
| E5  | `utils/git_sync.py:329` `fetch_all`           | `git fetch --all --no-prune`                           | every remote of the project repo                               | remote-tracking refs only (additive, never the working tree)                                               |
| E6  | `utils/git_sync.py:349` `pull_ff_only`        | `git pull --ff-only`                                   | the branch's upstream                                          | **updates the working tree**; opt-in for the project repo (`git_upstream_checker` mode defaults to `warn`) |
| E7  | `utils/git_sync.py:422`                       | `git remote prune <r> --dry-run`                       | every remote, per remote                                       | parsed for `[would prune]` markers                                                                         |
| E8  | `reference_repos/refresh.py:98,117`           | `fetch_all` + `pull_ff_only`                           | every remote of every discovered reference clone               | **updates those checkouts on disk**; default ON (see N6)                                                   |
| E9  | `handlers/status_line/git_branch.py:323`      | background `git fetch` on a TTL timer                  | project remotes                                                | remote-tracking refs; ahead/behind counts                                                                  |
| E10 | `scripts/upgrade.sh:198`                      | `curl -fsSL`                                           | `$HOOKS_DAEMON_UPGRADE_BASE_URL/$HOOKS_DAEMON_UPGRADE_REF/...` | **the downloaded shell script is `source`d** (line 251)                                                    |
| E11 | `scripts/upgrade.sh:307`                      | `git clone -c protocol.file.allow=always`              | `$HOOKS_DAEMON_CLONE_URL`                                      | becomes the installed daemon                                                                               |
| E12 | `install.sh:101`                              | `curl -LsSf https://astral.sh/uv/install.sh \| sh`     | astral.sh                                                      | **executed**, both streams discarded                                                                       |
| E13 | `install.sh:22,85`                            | `git clone`                                            | hardcoded daemon repo                                          | becomes the installed daemon                                                                               |

### Confirmed negative: nothing carries information out

I looked specifically for the outbound half of the brief — telemetry, bug-report
upload, a URL with query parameters built from local state.

- **There is no HTTP POST, PUT or upload anywhere in `src/`.** Every Python
  egress is a GET (E1, E3) or a git read. Grep over the whole package for
  `urlopen`/`requests`/`httpx`/`http.client` returns exactly two call sites, both
  listed above, both GET.
- **No URL is built from local state.** E1/E2 take a URL the operator typed or
  one recorded in a document's own frontmatter; E3 interpolates only a release
  tag and a fixed asset name; E4 is a hardcoded literal.
- **`issue_report/` never spawns `gh` and never fetches.** It renders a file to
  disk; publishing it is a separate, human/agent-driven `gh` call governed by
  `R-UPSTREAM-ISSUE-UNVERIFIED-BODY`. That is D-PUB's surface, not D-NET's.
- **No handler performs network I/O.** The `remote_docs` handlers read the local
  tree only; fetchers are injected from the CLI layer. This boundary is stated
  in `remote_docs/fetchers.py:25-26` and it holds.

### Confirmed negative: E4's response cannot inject context

`version_check` parses a ref name out of `ls-remote` and interpolates it into a
SessionStart context line (`version_check.py:245`). It is not exploitable:
`_compare_versions` (`:283-294`) requires every dot-separated part to parse as
`int`, and returns `False` (→ no advisory rendered) on `ValueError`. Only a
purely numeric-dotted string can reach the model. Git ref names also cannot
carry spaces or control characters. Recording this because "I looked and it is
fine" is a different result from "I did not look".

---

## Part 2 — Findings

### N1 — `urlopen` follows redirects, so the https-only invariant covers only the first hop

**Citation**: `src/claude_code_hooks_daemon/remote_docs/fetchers.py:98-116`

```python
parsed = urllib.parse.urlparse(url)
if parsed.scheme != "https":
    raise CaptureError(f"refusing to fetch non-https URL: {url!r}")
...
with urllib.request.urlopen(  # nosec B310 - scheme validated to https above
    request, timeout=_FETCH_TIMEOUT_SECONDS
) as response:
    return bytes(response.read())
```

Identically at `src/claude_code_hooks_daemon/install/relay_deploy.py:272-276`.

**What it allows**: `urlopen` uses the default opener, whose
`HTTPRedirectHandler.redirect_request` permits a redirect to any of `http`,
`https` or `ftp`. The scheme check runs once, on the URL the caller named.
A server at the validated https address can 302 to `http://…`, and the bytes
that are actually stored arrive over plaintext, modifiable by anyone on the
path. Two concrete outcomes:

1. **A vendored document records a lie.** `capture()` writes
   `source_url: https://…` — the URL that was *requested* — while the body came
   from an http hop. The document is then `fidelity: verbatim`, which the
   project defines (`CLAUDE/RemoteDocs.md:61`) as "the stored bytes ARE the
   response body". It is citable, greppable, and `remote_docs_routing` will
   **deny a WebFetch of the real URL** and send the agent to it instead.
2. **On the relay download path this reaches code execution.** Both
   `SHA256SUMS` and the relay binary are fetched by the same `fetch_fn` from the
   same base URL (`relay_deploy.py:303,321`). A redirect that captures both
   makes the digest check compare the attacker's manifest against the attacker's
   binary — they agree — and `deploy_relay_from_download` then does
   `target.write_bytes(binary_bytes)` and `target.chmod(0o755)`
   (`relay_deploy.py:340-341`). That binary is the hook forwarder: it runs on
   every tool call. The comment at `:286-291` claims "The digest is ALWAYS
   verified before anything is written to disk", which is true and insufficient
   — the digest is fetched over the channel it is meant to protect, so it
   attests to integrity-in-transit-corruption, not to authenticity.

Severity is bounded by `relay_source` defaulting to `None`
(`config/models.py:1487-1497`), so the download route is opt-in. The remote-docs
path is not opt-in in the same way — anyone running `remote-docs add` is on it.

**The class**: *a scheme/host restriction applied to the URL a caller supplies,
enforced by a client that follows redirects.* A member of this class is any
validation of a URL string that is not re-applied to the URL actually opened at
each hop. The test is mechanical: does the fetching client have a redirect
policy, and does the validation run inside it?

**Why the test suite does not catch it**: the word "redirect" appears nowhere in
`tests/` in connection with either fetcher — I grepped. Every unit test injects
`fetch_fn` or `https_fetch_fn` (`resolve_fetcher(https_fetch_fn=…)`,
`deploy_relay_from_download(fetch_fn=…)`), so the real `urlopen` is never
exercised. `relay_deploy.py:264` says so in as many words: "The real network
fetch — never exercised in unit tests (always mocked)." The scheme check is
tested against a `file:` URL passed in directly, which passes, because that test
asserts the first-hop behaviour that is not the defect.

**Detector hypothesis**: flag any `urllib.request.urlopen` / `requests.get` /
`httpx.get` call in `src/` that is not preceded (same function) by construction
of an opener with a redirect handler, or `allow_redirects=False`, or
`follow_redirects=False`. For urllib specifically, the positive signal is
`build_opener(...)` / a `HTTPRedirectHandler` subclass; its absence is the
finding. Likely false positives: a fetch of a URL that is a hardcoded literal
with no attacker influence (arguably still worth flagging — E3 *is* a hardcoded
literal and is still the worst case here, because of what it does with the
bytes); and any vendored/third-party code under `vendor/`, which the project's
standard `exclude_paths` already skip. Expected volume is 2 today, so this rule
is cheap and quiet.

**Confidence**: **High** on the mechanism — CPython's default opener installs
`HTTPRedirectHandler`, whose `redirect_request` accepts `http`, `https` and
`ftp` newurl schemes; this is documented behaviour, not an inference.
**Medium** on the relay scenario's practical reachability, since it needs the
opt-in `relay_source: download` plus control of a redirect from a github.com
URL (i.e. an attacker who already holds the release channel, or DNS/TLS). What
would settle the remote-docs half: a test that stands up a local redirect server
and asserts `https_fetch` refuses the downgrade. That is exactly the test that
does not exist.

---

### N2 — `remote-docs refresh` writes fetched bytes to disk without the sensitive-content guard that `add` applies

**Citation**: `src/claude_code_hooks_daemon/remote_docs/store.py:148-199` —
`refresh_document` has no `content_guard` parameter at all, and writes:

```python
result = capture(previous.source_url, fetch_fn=fetch_fn, ...)
...
path.write_text(result.content, encoding="utf-8")
```

Called from `src/claude_code_hooks_daemon/daemon/cli.py:6364-6370` with no guard
argument. Contrast `write_capture` (`store.py:133-138`), which does:

```python
if content_guard is not None:
    reason = content_guard(result.content)
    if reason is not None:
        raise CaptureError(f"refusing to vendor {url}: the fetched content {reason}. Nothing was written.")
```

**What it allows**: the guard's own docstring (`store.py:118-123`) states the
reason it exists — "a capture writes to disk from a CLI, bypassing the `Write`-tool
hook that would normally inspect content: without it, fetching an authenticated
page would vendor its secrets unexamined (Task 2.5)". `refresh` writes to disk
from the same CLI, past the same absent hook, and has no guard. So the concrete
outcome is: `bin/hooks-daemon remote-docs add <url>` is refused when the
response matches a public pattern or an entry in `.claude/block-words.secret`,
and `bin/hooks-daemon remote-docs refresh --all` on the *same URL* writes it.
Upstream only has to change after capture — which is the one thing `refresh`
exists to notice. The bytes then sit in the working tree, are read by agents,
and are surfaced by `remote_docs_routing`. `sensitive_content`'s commit gate
would catch them at `git commit`, so the exposure is bounded to the
working-tree/agent-context window rather than to history — the same window
`CLAUDE/RemoteDocs.md:139-141` already names as uncovered for Bash writes,
except that here it is the daemon's own supported command opening it.

**The class**: *two write paths to the same protected location where only one
carries the guard.* A member is any pair of functions in a module that both
reach `write_text`/`write_bytes` on the same tree, where one takes a validation
callback and the other does not. This is the F-BYPS shape scoped to a single
module, and it is decidable by reading one file.

**Why the test suite does not catch it**: `tests/unit/remote_docs/test_store.py`
tests `content_guard` three times (lines 82, 100, 117) and all three are
`write_capture`. The refresh tests in the same file cannot test the guard
because the parameter does not exist — there is no signature to write a failing
test against. A test suite proves the guard works on the path that has it; it
is structurally incapable of noticing the path that does not. This is the
"absent handler appears in no diff" argument (CHECKS.md `F-GAP`) applied inside
one module.

**Detector hypothesis**: for each module under `src/`, collect functions that
write to a configured tree root and check whether all of them accept (and
invoke) the same validation callback. A simpler, noisier first cut that would
have caught this one: flag a module where one public function has a
`*_guard`/`*_validator`/`*_check` parameter and a sibling public function
writing to the same destination type does not. Likely false positives: a
read-modify-write helper that is legitimately only called from the guarded
function (the guard already ran); a private `_write_*` that is the guarded
function's own implementation. Both are distinguishable by call-graph
reachability from a CLI entry point, which makes the rule implementable but not
trivial — worth reporting as **moderately noisy**, maybe 1 false positive per
handful of modules.

**Confidence**: **High.** The asymmetry is plain in the two signatures and the
call site passes nothing. The only judgement is severity, which I have set at
medium because the commit gate closes the durable half.

---

### N3 — Provenance frontmatter is rendered by unescaped string interpolation, so any field can forge the whole block

**Citation**: `src/claude_code_hooks_daemon/remote_docs/capture.py:162-186`

```python
return (
    "---\n"
    f"source_url: {source_url}\n"
    f"fetched_at: {fetched_at.isoformat()}\n"
    f"fidelity: {fidelity.value}\n"
    f"source_sha256: {source_sha256}\n"
    f"licence: {licence}\n"
    f"stale_after: {stale}\n"
    f"{method_line}"
    "---\n\n"
)
```

No `yaml.safe_dump`, no quoting, no rejection of `\n` or `---` in any value.
Three of these are caller-controlled: `source_url` (the CLI argument),
`licence` (`--licence`, free-form, no validation — `cli.py:9081-9085`, or a
`known_sources` config value), and `fetch_method` (a binary name).

**What it allows**: a value containing `\n---\n` **terminates the frontmatter
block early**, because `_FRONTMATTER_RE`
(`utils/markdown_format.py:37-40`) is non-greedy: `\A(---\r?\n.*?\r?\n---\r?\n)`
matches to the *first* closing delimiter. Everything the renderer writes after
that point becomes body text, and the parsed provenance is entirely whatever the
injected lines said. So a crafted value yields a document that legitimately
parses as `licence: MIT`, `fidelity: verbatim`, `stale_after: never` — and the
real values the daemon computed are inert prose below the fold.

The payoff is not the forged field but what the rest of the subsystem does with
it. `stale_after: never` means `check_staleness` (`store.py:274-286`) never
flags it, the SessionStart staleness sweep stays silent, and
`remote_docs_routing._read_advisory` (`remote_docs_routing.py:244-274`) never
fires — so an agent Reading the file gets *no* "this is a vendored copy, not
upstream itself" notice. A forged `licence` retires the unreviewed-licence
warning. And because `find_document` matches on the recorded `source_url`
(`lookup.py:109-116`), a document claiming
`source_url: https://docs.python.org/3/library/subprocess.html` causes
`remote_docs_routing` to **DENY a WebFetch of that real URL** and print
"ALREADY VENDORED — READ THE LOCAL COPY" with the local path
(`remote_docs_routing.py:229-242`). The agent is actively steered off the real
document and onto the forged one.

Note `source_url` is *not* protected by the https check upstream of it.
`_require_https` (`capture.py:85-89`) calls `urlparse`, and CPython's
`urlsplit` strips ASCII `\t\r\n` before parsing — I verified this on the
installed interpreter:

```
urlparse('https://example.com/a\nfidelity: verbatim\n')
  -> scheme='https' netloc='example.com' path='/afidelity: verbatim'
```

The check passes on the *stripped* URL while `capture()` hands the *original*
string, newlines intact, to `_render_frontmatter` (`capture.py:246-253`).

**Reachability, honestly**: via `https_fetch` (E1) the capture fails before
rendering, because `http.client.putrequest` rejects control characters in the
request target. Via `agent_browser_fetch` (E2 — the *default* fetcher) the URL
is passed as an argv element, where a newline is legal, and whether the fetch
succeeds depends on how `agent-browser` normalises it. Many HTTP clients strip
control characters exactly as CPython does, in which case the fetch succeeds and
the forged frontmatter is written. I could not settle this without running
`agent-browser`, which would be a network request. The `licence` and
`fetch_method` vectors have no such dependency at all — `--licence` reaches
`_render_frontmatter` untouched with no fetch involved in its handling.

**The class**: *a structured-format document assembled by string concatenation
from values that are not validated against that format's metacharacters.* A
member is any f-string or `%`/`+` construction of YAML, JSON, TOML, INI or a
delimiter-framed block where an interpolated value is not passed through the
format's own serialiser or validated to exclude its delimiters. The deciding
question is not "is this value trusted?" but "could this value contain a
newline, a quote, or the block terminator?" — because the trust judgement drifts
and the format question does not.

**Why the test suite does not catch it**: the capture tests assert the *shape*
of the rendered frontmatter for well-formed inputs and that `parse_provenance`
round-trips it. Round-tripping is precisely the property that still holds under
this defect — the forged document parses cleanly, which is the whole point. A
test would have to supply a value containing a delimiter and assert the parse
result disagrees with what the renderer was asked to record, and nothing in the
suite is written in that adversarial shape. There is also no test that
`_require_https` and `_render_frontmatter` see the same string.

**Detector hypothesis**: flag an f-string or concatenation that builds a line
matching `^\s*[\w-]+:\s*\{` (a YAML key with an interpolated value) where the
interpolated expression is not a literal, an enum `.value`, a `.isoformat()`
call, or a call to a known-safe serialiser. Likely false positives: log-message
formatting that happens to look like `key: {value}` (common — this would be the
dominant noise source, and the rule needs a scope restriction to functions whose
result is written to a file or returned as document content); rendered
human-readable reports using a colon layout, of which this repo has many in
`cli.py`. I would report this rule as **noisy as stated** and recommend scoping
it to modules that also import `yaml` or write `.md`/`.yaml` files, which cuts
it to a handful of candidates.

**Confidence**: **High** that frontmatter is forgeable by an unsanitised field
and that the early-`---` termination works as described (both the regex
non-greediness and the `rsplit` in `_load_frontmatter:141` are readable
directly). **Medium** on whether the `source_url` vector specifically is
reachable end-to-end through the default fetcher. What would settle it: pass a
newline-bearing URL to `agent-browser read` offline against a local server and
see whether it normalises or refuses. The `--licence` vector needs nothing
settled.

---

### N4 — `remote-docs refresh --path` accepts any path, so network content can overwrite a file outside the tree

**Citation**: `src/claude_code_hooks_daemon/daemon/cli.py:6354-6355`

```python
if args.path is not None:
    targets = [Path(args.path)]
```

No containment check against `tree`. `refresh_document` then reads that file,
takes its recorded `source_url`, fetches it, and writes the response back over
the same path (`store.py:171,194`).

**What it allows**: any markdown file anywhere on the filesystem that happens to
carry a parseable provenance block becomes a refresh target, and its contents
are replaced by whatever the recorded URL returns. `--all` is safe (it iterates
`list_documents(tree)`); only the single-path form is exposed. The contrast is
visible one file away: `remote_docs_routing._read_target`
(`remote_docs_routing.py:139-156`) does exactly the containment check this path
omits —

```python
tree = self._tree()
try:
    path.resolve().relative_to(tree.resolve())
except (ValueError, OSError):
    return None
```

so the project already has the right code, in the handler, and not on the write
path. Note also that `project_containment` keys on the `Write`/`Edit` tools and
on Bash command shapes; a write performed inside the daemon's own CLI process
passes none of those gates.

**The class**: same class as N2 in spirit but distinguishable and worth its own
statement: *a path taken from an argument and used as a write destination
without being re-anchored to the tree the command is scoped to.* A member is any
CLI handler where `--path`/`--file` flows to a write without a `relative_to` /
`is_relative_to` check against the command's configured root.

**Why the test suite does not catch it**: the refresh tests construct their
target inside a `tmp_path` tree and pass it, so the path is contained by
construction in every case. No test passes a path outside the tree, because no
test is written from the question "what if the argument is hostile?" — it is
written from "does refresh refresh?".

**Detector hypothesis**: flag a `cmd_*`/`_*` CLI function that converts an
`args.<name>` to `Path` and reaches a write call without an intervening
`relative_to`/`is_relative_to`/`resolve().startswith` check. Likely false
positives: commands whose entire purpose is to write where the user says
(`issue-report --output`, `--project-root`), which are legitimate and would need
an allowlist — I estimate that allowlist at 5-10 entries in this CLI, which is
maintainable but is real ongoing cost. Report as **moderately noisy**.

**Confidence**: **High.** The absence of the check is directly readable and the
sibling handler shows what the check should look like. Severity is medium rather
than high because the operator is the one naming the path — this is a footgun
and a privilege-boundary gap, not something a remote party triggers alone.

---

### N5 — `scripts/upgrade.sh` downloads a shell script from an unpinned, env-overridable URL and sources it

**Citation**: `scripts/upgrade.sh:178-205` and `:250-251`

```bash
ref="${HOOKS_DAEMON_UPGRADE_REF:-main}"
base_url="${HOOKS_DAEMON_UPGRADE_BASE_URL:-https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon}"
url="$base_url/$ref/scripts/lib/python_discovery.sh"
...
if curl -fsSL --max-time 30 -o "$tmp" "$url" && [ -s "$tmp" ]; then
```

then, at `:251`:

```bash
. "$discovery_lib"
```

**What it allows**: arbitrary code execution in the upgrade shell, from a URL
that is not pinned, not digest-verified, and not scheme-checked. Three separate
weaknesses stack:

1. **`$HOOKS_DAEMON_UPGRADE_BASE_URL` has no validation whatsoever.** Setting it
   to `http://…` produces a plaintext fetch of a script that is then sourced.
   Every Python fetch in this project enforces https (`fetchers.py:99`,
   `relay_deploy.py:273`, `capture.py:85`, `provenance.py:44`); this shell path,
   which has strictly worse consequences, enforces nothing.
2. **The ref defaults to `main`, a moving target.** Compare
   `deploy_relay_from_download`, which deliberately pins to the installed release
   tag — `relay_deploy.py:298-299`: "the download always matches the version
   actually installed, never 'latest'". The same repository holds both a careful
   pinned+verified download route and this one.
3. **No digest.** `relay_deploy` verifies sha256 before writing a binary it does
   not execute directly; this writes a script it sources immediately, unverified.

Worth stating plainly: `curl_pipe_shell` (`R-CURL-PIPE-SHELL`) exists in this
daemon to deny an *agent* the `curl … | bash` pattern. Fetch-to-temp-then-source
is that pattern with one extra step, and it is in the project's own upgrade path.
That is not hypocrisy on its face — a first-party upgrade script has a different
trust position from an arbitrary agent command — but the ref-pinning and
scheme-checking that would justify the difference are the parts that are missing.

**The class**: *a fetch whose response is executed, where the destination is not
pinned and the bytes are not verified.* The three questions that decide
membership: is the URL fully determined by the shipped code (no env override, no
floating ref)? is the response checked against a digest or signature carried
independently of it? is the scheme forced? A "no" to any of them puts a
fetch-then-execute in this class.

**Why the test suite does not catch it**: `tests/integration/test_upgrade_sh_*`
exercise the upgrade script's flow (forced checkout, rewritten tags, tmp
self-containment, stop bootstrap) against local fixtures — they never let the
network path run, because a test that fetched from raw.githubusercontent.com
would be flaky and slow. The fallback at `:219-224` is by design a
"last-resort" branch reached only when both local lookups miss, so it is also
the branch least likely to appear in any fixture. A green suite says the
upgrade works; it says nothing about where the script came from.

**Detector hypothesis**: over `*.sh`, flag any `curl`/`wget` whose output path is
later an argument to `.`, `source`, `bash`, `sh` or `eval`, or which is piped
directly into a shell; and separately flag any URL string built from a `${VAR:-…}`
expansion where `VAR` is not validated for scheme before use. Likely false
positives: documentation comments containing the install one-liner (this repo has
several — `install.sh:6`, `scripts/upgrade.sh:6`), which are text, not commands,
and need a comment-stripping pass. With that, the rule is quiet: I count 2 real
hits in the tree (this and N7).

**Confidence**: **High** on the mechanism and the missing controls — it is six
lines of shell and they say what they say. **Medium** on severity, because
exploiting the env-override arm requires an attacker who already influences the
environment of an upgrade run, and the default arm requires control of
raw.githubusercontent.com or the TLS path. The floating `main` ref is the part I
would raise regardless of attacker model: it means an upgrade of a *pinned*
release can source a script from an unreviewed branch tip.

---

### N6 — Reference repos are fetched *and fast-forwarded* from arbitrary remotes at every SessionStart, on by default, and a rule then forces the agent to read the result

**Citations**:

- `src/claude_code_hooks_daemon/config/models.py:1965` — `enabled: bool = Field(default=True, ...)`
- `src/claude_code_hooks_daemon/config/models.py:1978-1981` — `auto_pull: bool = Field(default=True, ...)`
- `src/claude_code_hooks_daemon/reference_repos/refresh.py:98,117` — `git_sync.fetch_all(path)` then `git_sync.pull_ff_only(path)`
- `src/claude_code_hooks_daemon/reference_repos/discovery.py:49-51` — a directory is governed iff it carries a `.git` entry. No remote allowlist, anywhere in the package.

**What it allows**: out of the box, every git checkout found within depth 4 of
`untracked/repos/` is contacted at session start — `git fetch --all`, i.e. *every
remote it has* — and then fast-forwarded onto disk if clean. Nothing constrains
which hosts those remotes point at; discovery's only test is the presence of
`.git`. `untracked/` is the project's scratch area, which is exactly where an
agent or a human drops a clone of someone else's repository without treating it
as a dependency decision.

The part that makes this D-NET rather than housekeeping is what happens next:
`R-REFERENCE-REPO-STALE` **denies a read of a clone that is behind**, and
`R-REFERENCE-REPO-NOT-VERIFIED` denies a read of one that has not been checked.
So the daemon pulls third-party content and then enforces that the agent reads
the freshest version of it. A commit pushed to any such repo lands in the local
filesystem at the next session with no diff shown, no changed-content advisory —
`RefreshOutcome.pulled` is reported, not what changed — and is then read as
authoritative reference material. Compare the treatment of the *other* subsystem
that vendors third-party text: remote-docs demands provenance, records a
fidelity claim and a licence, tracks staleness, and prints "this is a vendored
copy, not upstream itself" on Read. A reference clone gets none of that; it is
just files, indistinguishable in context from the project's own.

Two smaller edges in the same area:

- `git_sync._noninteractive_env` (`git_sync.py:119-124`) copies the full
  `os.environ` and sets `GIT_TERMINAL_PROMPT=0` plus SSH `BatchMode=yes`. That
  correctly prevents hangs, and it does not prevent a *configured credential
  helper* from being consulted for an https remote. A reference clone whose
  remote points at an attacker host causes the helper to be asked about that
  host at session start. Git's helpers are host-scoped, so this is a weak
  outbound path, not a credential leak — but it is the only place I found where
  egress could carry anything out, so I am naming it.
- `_stale_remote_tracking_refs` (`git_sync.py:414-440`) contacts **every** remote
  of the project repo at session start via `git remote prune --dry-run`.
  Additive and read-only, but it means an extra remote anyone ever added is
  pinged on every new session.

**The class**: *content fetched from a network location the project never
explicitly trusted, placed on disk where it is read as reference, with no
provenance marking and no allowlist of sources.* A member is any automatic
update path whose source set is derived from what is on the filesystem rather
than from configuration naming specific remotes.

**Why the test suite does not catch it**: the reference-repos tests inject a
`refresher` double (`sweep.py:85` exists precisely for that) or operate on local
fixture repos with local remotes. There is no assertion anywhere about *which*
remotes may be contacted, because the design has no notion of an allowed remote
— you cannot test a constraint that was never expressed. This is the F-GAP
shape: an absent control appears in no diff and no test.

**Detector hypothesis**: this one is doc-reading rather than code-reading. Flag
any configuration field whose default is `True` and whose docstring describes
network access or a filesystem mutation, where no sibling field constrains the
set of remote endpoints. Likely false positives: high — many default-on booleans
mention "fetch" or "check" harmlessly, and `enabled: True` on an advisory
handler would trip it constantly. I would report this rule as **too noisy to
enforce as written** and recommend the narrower, mechanical form instead: flag a
call to `fetch_all`/`pull_ff_only` whose `cwd` argument is not the project root,
and require that call site to name its source policy. That version has one hit
today (`refresh.py:98,117`) and is enforceable.

**Confidence**: **High** on the facts — defaults, absence of an allowlist, and
the read-forcing rules are all directly readable. **Medium** on whether it
should be treated as a defect rather than an accepted design trade: the plan
that introduced it (00401) argues explicitly for `enabled: True`
(`models.py:1938-1943`), so shipping on was a considered decision. What was
*not* considered anywhere I could find is the remote-trust question — the
docstring's reasoning is entirely about discovery finding nothing in projects
that never adopted the convention. That gap in the reasoning is the finding.

---

### N7 — `install.sh` pipes a third-party installer into `sh` with both streams discarded

**Citation**: `install.sh:100-104`

```bash
if command -v uv &>/dev/null || {
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
```

**What it allows**: `curl | sh` from a third party (astral.sh), unverified, with
stdout *and* stderr sent to `/dev/null` — so a compromised or simply failing
installer leaves no trace, and the `command -v uv` that follows is the only
signal. This is the exact construct `R-CURL-PIPE-SHELL` denies agents, and the
`2>/dev/null` is the exact construct `error_hiding_blocker` denies in authored
shell. Both of the project's own rules are broken by four tokens on one line.

Mitigation, which is real: this is the *legacy fallback* branch, reached only
when `$DAEMON_DIR/scripts/install_version.sh` is absent (`install.sh:91-96`),
i.e. installing an older tag. The modern path `exec`s Layer 2 and never reaches
it. Note also that the surrounding code was clearly revised for exactly this
concern one call later — `install.sh:108-116` explains at length why only stdout
is suppressed on the `uv sync` pre-warm "so a real failure is visible", while the
line above it discards both streams of a *remote code download*.

**The class**: same as N5 — fetch-then-execute with no pinning and no
verification. Grouped separately only because the remedy differs: N5 needs a
digest and a pinned ref; this needs the dead legacy branch removed or the
installer verified.

**Why the test suite does not catch it**: `tests/acceptance/test_install_sh_end_to_end.py`
exercises the modern path. Nothing tests the legacy fallback, because
constructing its precondition means checking out a tag old enough to lack Layer
2\. Dead-ish branches are where this class survives.

**Detector hypothesis**: covered by N5's detector (the `curl … | sh` arm). Add a
second, independent rule for `2>/dev/null` or `&>/dev/null` on any line
containing `curl`/`wget`/`git clone`, which is narrow and near zero-noise.

**Confidence**: **High** on the code; **Low** on practical severity, given the
branch is unreachable on any current install. Reported because a dead branch is
still a shipped branch, and because it contradicts two of the project's own
enforced rules — which makes it a credibility problem as much as a security one.

---

### N8 — `git clone -c protocol.file.allow=always` with an env-overridable URL

**Citation**: `scripts/upgrade.sh:305-308`

```bash
_CLONE_URL="${HOOKS_DAEMON_CLONE_URL:-https://github.com/.../claude-code-hooks-daemon.git}"
git -C "$PROJECT_ROOT" -c protocol.file.allow=always clone --quiet "$_CLONE_URL" "$DAEMON_DIR"
```

**What it allows**: `protocol.file.allow` was changed to `user` by default in
git 2.38.1 as the fix for CVE-2022-39253 (the `file://` submodule class). Setting
it back to `always` re-enables what that fix disabled, on the command that
produces **the installed daemon** — the code that subsequently runs on every
tool call. Combined with `$HOOKS_DAEMON_CLONE_URL`, which has no scheme check,
an influenced environment selects both the transport and the source.

I want to be accurate about the limit: this `clone` has no `--recurse-submodules`
and does not init submodules, so the specific CVE-2022-39253 chain is not
directly reachable here. The finding is the weakening itself and its placement:
a flag that exists to make local-path fixtures work (`scripts/dummy-client-repo.sh:51`
uses a local placeholder remote) is set unconditionally on the production
install path, where it buys nothing a real install needs.

**The class**: *a security default re-enabled in production code to satisfy a
test fixture.* Members are identifiable by the flag alone —
`protocol.*.allow=always`, `GIT_ALLOW_PROTOCOL`, `--no-verify`,
`PYTHONHTTPSVERIFY=0`, `verify=False`, `-k`/`--insecure`.

**Why the test suite does not catch it**: the fixture is the *reason* the flag is
there, so every test that touches this line depends on it being set. The suite
cannot flag what it requires.

**Detector hypothesis**: literal grep for a small list of known
security-downgrade flags across `*.sh`, `*.py` and CI config, outside test
directories. Likely false positives: near zero in source; the real noise is
documentation and comments explaining the flag, which a comment-strip removes.
This is the cheapest rule in this report and I would ship it first.

**Confidence**: **High** on the fact, **Low-Medium** on exploitability given the
absent submodule recursion. Reported as a hardening finding rather than a live
vulnerability, and explicitly marked as such so the register does not overstate it.

---

### N9 — Neither fetcher bounds the response size

**Citation**: `remote_docs/fetchers.py:116` — `return bytes(response.read())`;
`install/relay_deploy.py:276` — the same.

**What it allows**: a hostile or misbehaving server returns an unbounded body and
the whole thing is read into memory, then (for remote-docs) written to disk
inside the repository. Memory exhaustion in the CLI process, and a repository
polluted with an arbitrarily large file. The timeout at 60s / 30s bounds
*latency*, not *volume* — a slow-drip large response satisfies both.

The asymmetry is notable: the `agent-browser` path explicitly refuses a
truncated read (`fetchers.py:174-179`, "Half a page stored with full provenance
would read as a complete, citable document. Failing is the safer outcome"), so
the module has clearly thought about response integrity. The raw path has
neither a truncation check nor a cap.

**The class**: *an unbounded read of a remote response into memory or onto
disk.* Membership is decided by whether `read()` / `iter_content()` is given a
size limit and whether the accumulated total is checked.

**Why the test suite does not catch it**: the real fetchers are always mocked
(stated at `relay_deploy.py:264`), and every mock returns a few bytes. No test
returns a large body, because doing so would make the suite slow for a property
nobody asserted.

**Detector hypothesis**: flag `.read()` with no argument on an object derived
from `urlopen`, or `response.content` without a prior `Content-Length` check.
Likely false positives: `.read()` on local file handles, which is overwhelmingly
the common case — the rule needs the receiver to be traced to a urlopen result,
which makes it an AST rule rather than a grep. Moderate implementation cost,
low noise once written.

**Confidence**: **High** on the fact, **Low** on severity. Reported for
completeness of the D-NET inventory rather than as an urgent item.

---

## Part 3 — Register cross-check

`CLAUDE/Security/README.md` holds one category today — *authored path
resolution*, Defence `scripts/qa/check_authored_path_stat.py`. None of N1-N9 is
an instance of it: that category is about a stat predicate on a joined path in
the authored-path trees, and nothing here is a stat predicate.

Two of these findings are near a **documented** gap rather than a registered
one. `CLAUDE/RemoteDocs.md:139-141` already states that a Bash write into the
remote-docs tree escapes `remote_docs_provenance` and is caught only at commit.
N2 and N3 are both sharper than that note:

- N2 is the daemon's **own supported command** opening that window, not a Bash
  workaround.
- N3's consequence is not described anywhere: a forged `source_url` does not
  merely go unattributed, it makes `remote_docs_routing` **actively deny** a
  fetch of the genuine URL and redirect the agent to the forged file. The
  documentation frames the gap as an attribution problem; it is also a
  redirection primitive.

If a category is opened for this sweep, I would propose it be framed around N1
and N3 together — **"network response trusted beyond what was validated"** —
since both are the same failure of validating a *request* and then trusting a
*response* that need not correspond to it. N2 and N4 belong with the existing
bypass-inventory thinking (`F-BYPS`) rather than a new category.

Per the agent contract I have not written anything to the register: a category
with no Defence is a claim the register cannot make honestly.

---

## Summary table

| #   | Finding                                                                         | Severity | Confidence                                         |
| --- | ------------------------------------------------------------------------------- | -------- | -------------------------------------------------- |
| N1  | `urlopen` follows redirects; https enforced on first hop only                   | High     | High (mechanism) / Medium (relay reachability)     |
| N2  | `remote-docs refresh` skips the sensitive-content guard `add` applies           | Medium   | High                                               |
| N3  | Frontmatter rendered by unescaped interpolation; provenance forgeable           | High     | High (defect) / Medium (`source_url` reachability) |
| N4  | `refresh --path` has no tree containment                                        | Medium   | High                                               |
| N5  | `upgrade.sh` sources a fetched script; unpinned ref, no digest, no scheme check | Medium   | High (facts) / Medium (severity)                   |
| N6  | Reference repos auto-pulled from arbitrary remotes, default on, reads forced    | Medium   | High (facts) / Medium (is-it-a-defect)             |
| N7  | `install.sh` `curl \| sh` with both streams discarded (legacy branch)           | Low      | High (code) / Low (reachability)                   |
| N8  | `protocol.file.allow=always` on the production clone                            | Low      | High (fact) / Low-Medium (exploitability)          |
| N9  | Unbounded response read in both fetchers                                        | Low      | High (fact) / Low (severity)                       |
