# Plan 00625: the six points settled, and the threat model

**Standing.** The owner asked for the automatic upgrade and delegated the
settling of the open design points. Everything ruled here is settled by a
fable sub-agent under the owner's delegation, 2026-11-19. None of it is the
owner's own words, and a later owner message can overturn any of it.

**Where the rulings live.** DESIGN.md section 11a holds the rulings and their
requirements (`R<ruling>.<n>`), section 12 the threat model, section 13 the
tests. PLAN.md Phase 9 holds the builder's tasks. This report gives the
reasoning, the gaps found in the design as it stood, and what was and was not
checked. It does not repeat the requirement text.

**No code was written or run against a real checkout.** The branch was merged
with `main` first (one conflict, the plan index, resolved by keeping both
rows).

## The one decision everything else rests on

The design as it stood had default-ON consent (point 1) and fail-closed
signature checking (point 2) as separate items. Read together they answer the
objection the independent review raised against point 1, that the daemon
"grants consent the project never gave":

- no key ships with the daemon;
- an unattended run refuses without a key that a human added to that project
  and committed;
- so the shipped default changes nothing until a human in that project acts.

The key is the consent. The default only decides what happens once the key is
there. That is why default-ON for existing installs is ruled safe, and it is
the only reason. If a later change ships a key with the daemon, or lets a
release add one, ruling 1 no longer holds and must be re-decided.

## Reasoning per ruling

### 1. Default ON for existing installs

- **Why not stay off for existing installs.** With ruling 2 an existing
  install is inert either way; the choice is only whether a project that adds
  the key must also add a config line. Requiring both adds a step and no
  safety, because the key step already needs a human.
- **Why a soak period (R1.6), which nobody asked for.** Signing proves who
  published a release, not that it works. The health check catches a daemon
  that will not start, and nothing else. A day's delay, measured from the
  clone's own first sighting, lets a bad release be withdrawn before any
  unattended install takes it, and it costs nothing an attacker can use:
  deleting the sighting record only lengthens the wait. This is my addition
  and the easiest ruling for the owner to overturn or retune.
- **Why enforce the opt-out in the entry script (R1.5).** The review judged
  M4 harmless because `--unattended` only adds refusals. That stops being
  true once the unattended route is the only one that needs no human: a
  project that said "off" should get a refusal from the code that starts the
  upgrade, not only silence from the notice.
- **Why a `started` record (R1.7).** The review left "kill -9 mid-run" as not
  verified, and by reading no record is written. A release that crashes the
  host mid-upgrade would then be retried at every session start.
- **The notice.** Round 4 found that a notice tied to the first invitation
  can never show without a key. It is ruled to show once regardless, in the
  wording that fits the state, and again once when a key first appears. A
  line in a session nobody reads is weak notice, so the upgrade's own commit
  message carries it too.

### 2. Signature verification and the trust model

- **A project file, not a daemon file.** A key that arrives with the code it
  verifies proves nothing about that code. A key inside the installed version
  that verifies the NEXT version is a real model (most package managers use
  it), and I rejected it for now: it turns one compromised attended upgrade
  into a permanent unattended channel, and it would make the default
  genuinely automatic with no human act, which removes the footing of ruling 1.
- **The file is writable by the agent, and that was the largest hole.** "No
  environment variable or flag can redirect it" is true and beside the point
  when the agent can append a line. Three layers are ruled: the key must be
  committed (so a change is a visible commit), a built-in write guard, and a
  key command that needs a terminal and is denied to the agent. None of these
  stops an agent that is fully compromised and has a shell, and DESIGN says
  so. That attacker needs no upgrade to do harm, so it is outside what the
  signature defends.
- **What the signature does defend:** a forged or moved tag, a hijacked
  repository or hosting account, and a network attacker. Those are the
  attacks that unattended running makes worse, because the human who might
  have read the script is gone.
- **The key was not taken from the tags.** A signed tag embeds its public
  key. Extracting it would be fetching the key from the same place as the
  tag. I did not do it, and R2.3 forbids the tooling from doing it.
- **Expiry is not revocation.** As I understand git, an allowed-signers
  validity window is checked against the tagger date, which the signer
  chooses, so a stolen key can sign a backdated tag. I did not run this; V25
  makes it a tested fact. Whatever V25 shows, revocation is ruled to mean
  removing the key.
- **Rotation never rides on a release.** A release may subtract trust and
  never add it. Otherwise the old key's holder (or thief) appoints the next
  key for ever.
- **The daemon's own repository.** Off, refused, and no key file. The one
  addition is a release gate (R2.7): once installs fail closed on signatures,
  an unsigned release silently stops every unattended upgrade everywhere, and
  the release procedure is the place to catch that.

### 3. The script runs from the verified tag

- The round 3 design already had the right shape: the installed version is
  the trust root, it verifies, and the tag's own Layer 1 runs.
- **Gap found: Layer 2 resolves the tag name again.** Layer 1 verifies and
  checks out a commit; Layer 2 then looks the tag up by name. Anything that
  moves the local tag ref in between (another agent's `git fetch --tags --force` in the clone needs no lock) changes what Layer 2 deploys. R3.4
  binds Layer 2 to the commit id.
- **Gap found: skill scripts fetch themselves from `main`.** `daemon-cli.sh`,
  `health-check.sh` and `init-handlers.sh` self-bootstrap from a base URL,
  with the checksums fetched from the same place. An unattended run that
  calls them runs unsigned code. R3.2 switches that off for the run with the
  existing `HOOKS_DAEMON_SKIP_BOOTSTRAP`.
- **Gap found: replace objects.** A `refs/replace/` entry leaves the tag's
  signature valid while `git show` and the checkout read a different commit.
  It needs local write access, so it is hardening and not a remote attack,
  but it is one environment variable.
- **Checked:** the upgrade's dependency install is `uv sync --frozen` and the
  lock file carries hashes, so dependencies are pinned by the signed tree.

### 4. Clean stop at any step that asks

- **The owner's wording and the round 4 build disagree.** "Leaves the current
  version running" can only be met before deploy. Round 4 handles questions
  after deploy, in skill text, because post-upgrade tasks carry no
  machine-readable marker.
- Ruled: add the marker, have the gate read it before deploy, and so move
  every question that can be known in advance to a point where nothing has
  changed. What remains after deploy is left undone and written to a file
  that is reported every session, because a one-line notice in an unattended
  session is read by nobody.
- **Not rolled back for a question.** The new version passed its health
  check. Rolling it back because a task wants a human would repeat at every
  release.

### 5. Dirty-tree refusal limited to the daemon's paths

- Safe in itself: the upgrade stages only the owned paths.
- **Gap found: staged files.** Once unrelated dirty files no longer block,
  another agent's STAGED changes ride along in the upgrade's commit unless
  the commit names its paths. R5.3.
- **Gap found: the list exists three times** (Layer 1, the Python pre-check,
  skill step 7). They will drift. R5.2.
- "Retry at the next opportunity, never in a loop" is ruled to mean the next
  SessionStart whose pre-check passes, with the pre-check mirroring the
  refusal so that no doomed run is invited.

### 6. One line

- The limits moved out of the prompt and into code long ago; the line only
  has to be honest about what it is and name the single route.
- Nothing is injected while there is no usable key. A line that says "you are
  authorised to upgrade" beside a refusal that says "no key" is an invitation
  to an agent to go and find a key.

## Threat-model gaps found in the design as it stood

01. The signers file could be changed by the agent it is meant to constrain.
02. Layer 2 re-resolved the tag by name after Layer 1 verified it.
03. Skill scripts self-bootstrapped from `main` during an unattended run.
04. Replace objects and git location variables were not neutralised.
05. `ssh-keygen` was taken from the caller's `PATH`.
06. The opt-out and the self-install refusal lived only in the notice.
07. A run killed outright left no record, so it would be retried each session.
08. A rollback that itself fails had no stop.
09. A signature mismatch wrote no record, so a release signed with a new key
    would be attempted and refused at every session start.
10. Staged files of other agents could enter the upgrade commit.
11. The MAJOR check could take its baseline from the tracked stamp (review
    M12) and the release-state check missed a dangling symlink (review M6).
12. The lock path was not required to be a regular file (review M7).
13. Nothing said where an unattended agent may read release text from.
14. No release-side check that a published tag verifies.
15. A validity window was at risk of being documented as revocation.
16. A bad but honestly signed release had no defence beyond the health check.

## What I checked, and what I did not

- **Read:** DESIGN.md, PLAN.md, the adversarial review, the round 3 and round
  4 handoffs, and `scripts/lib/release_tag_verify.sh` in full.
- **Checked by search:** the origin-rewrite refusal in Layer 1; the
  `uv sync --frozen` install and the hashes in the lock file; the
  self-bootstrap fetch in three skill scripts and its off switch; the
  existence of a `write_protected_paths` handler to build R2.4 on; the names
  of the redirecting environment variables.
- **Not run:** any upgrade, any verification, any test. The `valid-before`
  behaviour, the git minimum version (2.34 is from memory), and how the gate
  and the skill locate release text today are stated as requirements with
  tests, not as verified facts.
- **Not read:** `upgrade.sh` and `upgrade_version.sh` beyond the searched
  lines. Line references in the handoffs were taken as given.

## Still needed from the owner

- The release-signing public key, added to each project by a human with the
  R2.3 command once it exists. Nothing in the build waits for it; every test
  uses a throwaway key.
- Where third parties are to obtain the key's fingerprint. It must not be the
  repository that publishes the tags as the only source.
- Any of the rulings the owner wants changed. The two that add most beyond
  what was asked are the soak period (R1.6) and the requirement that the key
  be committed (R2.1).

## Process note

The task asked for a commit trailer naming a different model from the one
the session's attribution rule names. The session rule says only the user's
own instruction overrides it, so the commit carries the session's line.
