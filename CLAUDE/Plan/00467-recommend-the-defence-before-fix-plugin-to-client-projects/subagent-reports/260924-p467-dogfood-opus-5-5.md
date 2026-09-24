# Plan 00467 Tasks 1.2 and 1.3 (drafting): DBF plugin dogfood report

The scope was evaluation and drafting only. Only files inside the plan folder were edited, and
nothing was committed or filed.

## What changed in the plan folder

- `PLAN.md`:
  - The Overview now says the plugin is enabled through `.claude/settings.local.json`, not
    `.claude/settings.json`, and names the cache location.
  - Task 1.2 links EVALUATION.md and stays **unticked**.
  - Task 1.3 lists the drafts.
- `EVALUATION.md` (new): evidence for each criterion, with plugin file:line citations.
- `upstream-drafts/01`–`06` (new): four issue drafts and two comment drafts.
- `JOURNAL/`: one `finding` entry, appended through `mkplan.bash --journal`.

## Why Task 1.2 is not ticked

Criterion 3 (auto-trigger) has no observed evidence. It is judged from the description only.

- The skill was not offered to this session: it is not in the Skill list, and the agent types
  are absent.
- A headless `claude -p --plugin-dir` probe proved the plugin loads: `init` lists
  `defence-before-fix:dbf` and both agents.
- But the probe stopped at "Not logged in".

One logged-in run of the three probe prompts (EVALUATION.md, last section, and draft 02)
closes the criterion. The scratch repository for it is ready at
`untracked/scratch/p467/trigger-probe/`.

## Findings by criterion

1. **Detectors: not found.**
   - SKILL.md:42-58 knows only composer and package keys, plus the register.
   - The register has no shell row. Its only Python tool graded green is pylint, which this
     repo does not run.
   - The fallback never looks at `scripts/qa/`, `llm_qa.py` or `CLAUDE/Security/`, which
     contradicts SPEC section 2.
2. **Real run: done by hand** on the `resolve_venv.sh` `sleep` watchdog (766677c1).
   - Class and hazard were written.
   - An emulated independent searcher found **4 more candidate instances**:
     - `scripts/venv_bootstrap.sh:443` and `:474` (`date`);
     - `scripts/install/venv.sh:427` (`date`);
     - `scripts/install/daemon_control.sh:40-43` (`pgrep`).
   - I reproduced the first idiom.
   - A detector was proposed (a declared hostile-`PATH` surface inventory plus a
     `scripts/qa/check_*.py` checker), and was not built. The steps from the red commit onward,
     and the conformance review, were not run.
3. **Auto-trigger**:
   - The "QA tool prints Defence Before Fix" trigger never fires here.
   - The "red QA run" trigger is broad, and would often re-run the method where a detector has
     already fired.
   - Under Plan 00463, `conformance-reviewer`'s two entry-point runs need the targeted
     `llm_qa.py <tool>` form.
4. **Spec duplication: versions agree** (1.0.1 / 1.0.0 / 0.2.0, all 2026-09-08). A fresh fetch
   today is byte-identical to the plugin's copies.
   - The remote-docs SPEC and DETECTOR-SPEC are HTML conversions. That corrects the 18:00
     journal entry's "byte for byte".
5. **Token cost** (bytes / 4):
   - Always-on is ~285 tokens, which matches the ~290 projection.
   - An invocation is at least ~5.7k, and ~20k in this repo (the register read), against the
     ~1.6k projection. The projection counted only the SKILL.md body.
6. **Report conventions**: the emulated searcher refused to write its named file. It cited the
   harness's sub-agent note, and the report survived only through the Plan 00460 auto-save.
   New evidence for upstream #3.

## For the coordinator

- **Upstream #3 is not "the plugin's name in hook output"**, as the brief said. It is "Both
  agents are told to write a report file but have no Write tool". #2 is toolchain discovery.
  Neither has comments. No issue about the plugin's name in hook output exists upstream.
- **Niggles ledger.** The four candidate instances, and the missing detector for the class,
  belong in the open niggles ledger. The brief confined me to this plan folder, so I have not
  appended them. Whether each surface truly must survive a hostile `PATH` still needs judging.
- **Plan 00468.**
  - `installed_plugins.json` still says `scope: project` after the move to local, and so does
    `claude plugin list`.
  - The Plan 00307 dispatch-declaration advisory did not recognise "File to write to: <path>"
    as a declaration.
- **Draft 04 part 1** rests on the vendored plugins reference: `CLAUDE_PLUGIN_DATA` is absent
  from the Bash tool's environment. It has not been seen live.
- **Draft 05** has a `#N` placeholder for draft 01's issue number.
- **Recovery cron.** A PostToolUse hook asked for a recovery-cron check. As a sub-agent I left
  crons alone; the coordinator owns them.

## Recommendation for Task 1.4: no-go now; go once the named shortfalls are fixed

**What the plugin gets right:**

- It is safe to have enabled: no hooks, read-only agents, and one pre-approved script.
- It is cheap always-on (~285 tokens).
- Its spec copy is current.
- The method found real defects here on its first run.

**Why not recommend it to every client yet:**

1. **Upstream #3 (every client).** The two agents cannot meet their own output contract. In a
   client without this daemon's auto-save, the searcher's and the reviewer's reports are lost,
   or they get written through an unguarded Bash heredoc.
2. **Upstream #2 plus draft 01 (every non-PHP/TS client).**
   - The skill cannot find a Python, shell or bespoke project's existing detectors.
   - Its fallback steers toward a new register tool. For Python that tool is pylint, whatever
     the project runs.
   - A recommendation from this daemon would reach many projects that are neither PHP nor
     TypeScript.
3. **Daemon side (Plan 00468).** Recommending a plugin to clients should wait until the daemon
   copes with it:
   - P2: plugin agents invisible to the Plan 00460 read-only logic.
   - P3: `format-markdown` and `housekeeping` rewrite installed plugin files.
   - Task 1.2: the settings-template test.
4. **Before sign-off.** Run the live auto-trigger probe (draft 02). If "red QA run" fires the
   full method on lint failures, each false trigger costs ~6–20k tokens plus two sonnet
   sub-agents. That would need to be in the recommendation's "what it costs" field, or fixed
   upstream first.

**Not blocking**:

- Draft 03 (reviewer cost), which matters once Plan 00463 lands.
- Draft 04 (cache location, version `-`).
- The invocation-cost gap.

**Once 1–3 are fixed**, recommend it to all clients, with the measured costs stated.

**Optional early step**: an opt-in recommendation for PHP and TypeScript clients alone, after #3
and 00468 P2/P3.
