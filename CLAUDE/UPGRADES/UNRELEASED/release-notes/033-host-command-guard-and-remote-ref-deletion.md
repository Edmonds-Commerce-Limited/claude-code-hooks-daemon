# Callout: five dangerous commands are now denied, three of them human-only

**Plan**: 00483
**Audience**: everyone

The owner-approved table for the five commands the dangerous-invocation corpus listed as uncovered is now enforced. A new `host_command_guard` handler (on by default) denies `docker run -v /:/host` (also `--volume`, `--mount type=bind,source=/,...` and `docker create`) and `gh auth token`, which prints the OAuth token into the transcript; a token piped to or substituted into another command is allowed. It also denies `pip install --index-url`, `-i` and `--extra-index-url` naming a non-PyPI index, and `crontab -r`, as human-only commands: the denial tells the agent to stop and ask the human to run the command, with no escape hatch. `destructive_git` gains the same human-only denial for deleting a ref on the remote, `git push --delete <name>` and `git push <remote> :<name>`.

PyPI means `https://pypi.org/...` or `https://files.pythonhosted.org/...` and nothing else; an index held in a variable is not judged. `git tag -d`, `git reset --keep`, `truncate -s 0` and `rm -rf` stay allowed, and a mention of any denied command in an `echo`, a `grep` pattern or a commit message is not a command. A project that mirrors PyPI privately sets `host_command_guard.enabled: false` or asks the human to run those installs.
