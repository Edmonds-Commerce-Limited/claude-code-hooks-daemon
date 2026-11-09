# Task 3.2 report: arm64 release assets

## What was delivered

1. **`.github/workflows/release-assets.yml`** (new). Triggers on a `v*` tag push and
   on `workflow_dispatch` with a required `tag` input. The workflow token is
   `contents: read`.
   - `build` matrix: x86_64 on `ubuntu-latest`, aarch64 on `ubuntu-24.04-arm`,
     `fail-fast: false`, 20 min timeout. Each leg checks out the tag and validates
     it (semver regex, read through `env` to avoid injection). It asserts
     `uname -m`, runs `rustup target add`, then runs `relay/build.sh` and
     `screen/build.sh`, using the same recipe as Task 3.1's `native-builds`.
     It checks each binary's ELF machine with `readelf -h`, executes both
     (relay exit 13 = usage error; screen `--dump`), and uploads
     `hooks-relay-<triple>` and `hooks-screen-<triple>`.
   - `publish` job (needs `build`, permissions `contents/id-token/attestations: write`, 60 min timeout): downloads the artifacts with `merge-multiple` and
     writes one `SHA256SUMS` over all four binaries (`LC_ALL=C`, asserting exactly
     4 lines). It runs `actions/attest-build-provenance@v2` on `dist/hooks-*`,
     then `gh release upload --clobber` and reads the release back.
   - **When the release does not exist yet:** RELEASING Step 14 pushes the tag
     BEFORE `gh release create`, so the publish job polls `gh release view` for
     up to 45 minutes and then fails loudly, telling you to re-run with
     `workflow_dispatch tag=vX.Y.Z`. It deliberately does NOT create the
     release: if it did, the session's `gh release create` would fail with
     "already exists", and the release would be published with no notes.
2. **Selection by architecture.** In `utils/relay_host.py`, a new
   `relay_target_for_machine(machine)` maps x86_64/amd64 and aarch64/arm64 (any
   case) and returns None for anything else. `host_relay_target` now uses it.
   `install/relay_deploy.py` gains `PUBLISHED_RELAY_TARGETS` (both triples),
   `relay_asset_name_for_target` and `relay_asset_name(machine=None)`.
   - `deploy_relay_from_download` fetches `hooks-relay-<host triple>`. A host
     with no published asset is refused before any fetch, and the message
     names the OS and machine.
   - `_deploy_auto` and the failure banner now treat aarch64 as having a
     download fallback.
   - This mirrors Plan 00569's `screen_target_triple` in the supervisor.
   - Nothing downloads hooks-screen today, so its asset is published only.
3. **RELEASING.md Step 14.** The manual relay build and upload block is
   replaced with a check of the workflow's run, its five assets and
   `gh attestation verify`. `scripts/release/build_relay_release_assets.sh`
   is deleted: nothing else referenced it, and its x86_64-only `SHA256SUMS`
   would clobber the merged one.
4. **Release note** `CLAUDE/UPGRADES/UNRELEASED/release-notes/006-arm64-release-assets.md`,
   numbered 006 per the coordinator (005 landed on main). A one-clause update
   to `docs/guides/HANDLER_REFERENCE.md`.

## Tests (written first, RED confirmed by ImportError)

- `tests/unit/install/test_relay_asset_selection.py`: covers the machine
  mapping, the asset names, the download per architecture, an unsupported
  machine refused before any fetch, `auto` on aarch64 without a toolchain
  falling back to download, and the banner.
- `tests/integration/test_ci_release_assets.py`: covers the workflow
  structure. Its matrix must equal `PUBLISHED_RELAY_TARGETS`, which ties the
  workflow to the download code. It also checks that RELEASING no longer
  uploads by hand.
- `tests/unit/install/test_relay_platform.py`: the aarch64 auto test now asserts
  that no x86_64 URL is fetched, instead of asserting that nothing is fetched.

## Notes

- If an arm64 host installs a release from before this change, its download
  now reaches `SHA256SUMS` and reports "has no entry for
  hooks-relay-aarch64-…". That is an advisory, never fatal, as before.
- `qa.yml` is untouched, so it does not conflict with #180.
- The worktree had no venv. QA ran with `HOOKS_DAEMON_VENV_PATH` set to main's
  py313 venv and `PYTHONPATH` set to this worktree's `src`.
