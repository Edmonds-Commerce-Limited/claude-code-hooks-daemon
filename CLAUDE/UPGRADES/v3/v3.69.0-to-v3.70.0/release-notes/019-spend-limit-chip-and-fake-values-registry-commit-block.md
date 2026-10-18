# Callout: a `$` spend-limit chip, and an opt-in commit block for the fake-values registry

**Plan**: 00474
**Audience**: everyone

Behind a Claude apps gateway that sets you a spend limit, Claude Code's Status payload carries `rate_limits.spend_limit`. The status-line usage segment now shows it as a `$` chip beside the 5h and 7d chips (`$5%`, or `$ 62% 3h 0m` once it passes the warning level), in the same colour bands. The percentage is not capped at 100, so an exceeded limit reads `$ 140%` on red; a value above 10000 is treated as malformed. The chip is hidden when the field is absent or malformed, and the usage ceiling and pause gates still look only at the 5h and 7d windows.

The docs QA check `unlisted-fake-value` now also runs at the commit gate. It denies a commit that adds a `.claude/fake-values.yaml` entry which is not visibly fake (the word `fake`, or one character repeated eight times), or that stages a registry which cannot be parsed. Entries already in HEAD are not blamed on the commit.

**Other projects must opt in to the block.** The check ships advisory. To get the denial, set it in `.claude/hooks-daemon.yaml`:

```yaml
documentation:
  qa:
    check_modes:
      unlisted-fake-value: block
```

This repository sets it already. Without the key the same finding is shown as advisory context at commit time.
