# Callout: the secret guard judges a link from the command's own directory

**Plan**: 00614
**Audience**: client projects

A symlink with an innocuous name that points at a protected file was denied when spelled as an absolute path, but three spellings reached the file's content past `secret_file_guard`:

- A relative Bash word naming the link (`cat link`, `cat < link`, an interpreter one-liner's `open('link')`). The daemon runs from `/`, so the link was looked up there instead of in the command's working directory. It is now resolved from the hook's `cwd` (and every literal `cd` target), and a link anywhere on the path counts, not only the last component. A relative `Read` or `Grep` path is judged the same way.
- A recursive search (the Grep tool, `grep -r`, `rg`) rooted at a directory link that leads out of the project, typically into another checkout from a worktree. The protected-file index lists only the project, so such a search is no longer vouched for and is denied.
- A glob under a directory link (`cat dlink/*`) that leads out of the project. Plan 00612 already matches such a glob with its literal directory resolved; a target outside the project is now denied too.
- A `cd` the command makes anywhere bash runs it: in a subshell `( )`, a brace group, after `if`/`while`/`then`, in a `$( )` or backtick substitution, in a quoted `bash -c` body, and `env -C`/`--chdir` and `git -C`. All of these now move where a relative link is read, for both the text scan and a recursive search.
- A glob whose wildcard sits in the component that names the directory link (`cat dl*/*`, `cat pl*/sub/*`, `grep -r x dl*`). The matching links in the literal parent are listed and judged. A glob whose first component is wildcards only (`*/*`) still names no place and is allowed.
- A command an exemption clears (an allowlisted consumer such as `ansible-playbook` with the protected path in flag position, a grep whose protected mention is only its pattern, or one naming an encrypted-at-rest file) no longer clears a relative link to a protected file beside it.

Behaviour change: a recursive search or a glob through a link from inside the project to a directory outside it is denied even when that directory holds no protected file. The deny message now says that a link to a directory outside the project is the cause, names the link, and says to run the command from the checkout that holds the target. It also names the first configured protected glob, because no particular file matched.

- A `cd` spelled `builtin cd`, `command cd`, or with a redirection before it or before its operand (`>/dev/null cd x`, `cd 2>/dev/null x`), and the chdir options `sudo -D`/`--chdir` and `tar -C`/`--directory`. All of these now move where a relative word is read.
- A glob with no slash (`*`, `i*`, `*/*`) read after a `cd` into a directory link that leads out of the project. It is now denied like `./*`.

Behaviour change: a `cd` whose target bash computes (`cd "$D"`, `cd $(pwd)/x`, `cd -`, a bare `cd`) now makes relative words and search roots be read from the project root, and from every project directory that holds a link, as well as from the hook's `cwd` and every literal target. Before, they were dropped. So `cd "$D" && grep -r foo .` is now judged over the project root. A variable the same command assigns literally (`D=x; cd "$D"`) is put in, in addition to those directories rather than instead of them. A globbed target (`cd inn?r`) is expanded on disk, listing at most 512 directories; a wider glob is judged like a computed target. A wrapper before a command with a chdir option (`sudo tar -C d`, `nice git -C d`, `nohup env -C d`) no longer hides the option. The directories that hold a link are found by a scan of at most 512 directories (see the next-but-one change for what happens past that).

Behaviour change: if working out where a command's paths lead raises an error, the call is now denied rather than allowed with an advisory. This covers placing a directory it moves to, a link or a glob. Before the fix, a `cd` to a single name over 255 bytes made every protected read in the same command go unjudged. A failed `cd` (to a name that is not a directory) keeps the directory a recursive search was already in, as bash does for a command after `;` or `||`.

Behaviour change: when a command moves into more than 16 existing directories, a relative word that could pass through a link in one of them is denied rather than resolved from each, and the deny message says to split the command. The same rule applies to the quarantine-artefact guard, which shares the index. A path that is outside the project as spelled is judged as before, and an ordinary relative word that is not a link behaves as before.

Security fix: when the scan of a Bash command stopped early (a brace expansion past the enumeration cap, the scan deadline, a word it could not read, or an internal error), only the literal paths in its text were judged, so a recursive search in the same command (`echo {a..z}{a..z}{a..z}; grep -r x dir`) was allowed with the not-judged advisory. Such a command is now denied whenever it holds a recursive search or a glob, and the deny says the scan stopped before it finished. A command with neither keeps the advisory. A Grep tool call whose check stopped early is denied the same way.

Behaviour change: any Bash command holding a glob character (`*`, `?`, `[`) or a recursive search whose scan stops early is now denied, where it was allowed with the not-judged advisory. Split a command that trips this, or drop the large brace expansion beside it.

Behaviour change: after a `cd` whose target bash computes (`cd "$(pwd)/x"`), or a globbed `cd` that matches nothing, a glob read (`ls *.md`) is denied in a project that holds a directory link leading out of the project, because the shell could be inside that link. A plain relative path is still judged as before. Spell the directory literally to avoid it.

A `cd`, `env -C`, `sudo -D`, `tar -C` or `git -C` named by its path (`/usr/bin/env -C d`) is now read like the bare command.

A command with many `cd`s to directories that do not exist no longer makes the search check's cost grow without bound: past 64 candidate directories every later read is judged over every indexed file and over every directory link a move could reach.

A `cd` operand that is an extended glob (`@(x)`, `+(x)`), a relative `cd` in a command that names `CDPATH`, and `eval cd x` are now judged like a computed `cd`.

A globbed `cd` that matches more than 16 directories is judged like a computed `cd` rather than followed match by match, which keeps the guard's cost bounded (`cd */*/*` over a wide tree no longer takes seconds).

A computed `cd` is now also judged from inside each directory link in the project, not only from the directories that hold a link, so `cd $(echo link) && cat .e*` is denied when `link` leads out of the project. At most 512 directory links are considered.

Behaviour change (fail closed): the link scan behind a computed `cd` now reports whether it finished. It does not finish when the project has more than 512 directories (most real repositories), more than 512 directory links, or a link whose target cannot be stat-ed for a reason other than a loop. Then any relative word after the computed `cd`, and any recursive search or directory reader after it, is denied, because the shell may be in a directory the scan never reached. Before, the scan logged that it stopped and the call was allowed; one link loop early in the project could also end the scan silently. In a large project, `cd "$D" && make test` or `cd $(pwd)/x; ls` is therefore denied; spell the directory literally instead. `cd "$(git rev-parse --show-toplevel)"` (or the backtick form) is not a computed move: it is placed at each ancestor of where the command is, up to the project root, and needs no scan. A command that names a `GIT_` variable is still judged as computed. The unquoted `$( )` form placed before a recursive search (`cd $(git rev-parse --show-toplevel) && grep -r x d`) is still denied in a large project; quote it. A quoted `bash -c` body holding `&&` or `;` after a `cd` (`bash -c 'cd sub && cat f'`) is read as a computed move and is denied in a large project too.

After a computed `cd`, a relative word of several components (`cat a/late`) is also resolved from each directory above a scanned link that its leading components lead into, so a link one or more levels below where the shell may be is judged. Behaviour change: a recursive search or directory reader after a computed `cd` is now judged as reading every directory link in the project too, so in a project holding a directory link out of the project, `cd "$D" && grep -r x sub` is denied.

The scan is reused only within one tool call. Before, it was kept for 5 seconds, so a link made by one call could be read through by the next.

A chdir option inside a short-option cluster (`env -iC d`, `sudo -nD d`, `env -iCd`) or abbreviated (`env --chd=d`, `env --ch d`, `sudo --chd=d`) now moves where a relative word is read, as does `exec` before the command (`exec env -C d`, `exec -a name env -C d`).

A Grep tool call with no `path` is judged at the hook's `cwd` when that directory passes through a link, so a session whose directory is a link out of the project is denied a search there. A pathless Grep from an ordinary directory is judged as before.

`cd "$(git rev-parse --show-toplevel)"` is not trusted when the command defines a function or alias, changes `PATH`, sets `core.worktree` or names a `GIT_` variable; it is then judged as computed. Otherwise it is judged as computed too, with each ancestor added, but a link scan that did not finish does not deny it. The quarantine-artefact guard now denies a call whose paths could not be placed, as the secret guard does, instead of allowing it with an advisory.

Upgrade: nothing to do.
