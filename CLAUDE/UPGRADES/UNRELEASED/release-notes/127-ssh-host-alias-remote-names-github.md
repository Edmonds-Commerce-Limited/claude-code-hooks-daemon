# Fix: a `github.com-<suffix>` ssh host alias remote is read as GitHub

**Plan**: 00474
**Audience**: everyone

A remote cloned through an ssh config host alias, the common multi-key idiom `git@github.com-<suffix>:owner/repo.git` (or `ssh://git@github.com-<suffix>/owner/repo.git`), now names `github.com`. Before, `branch-reject request <name> --remote-only` passed the alias to `gh -R` as the host and always refused ("error connecting to github.com-<suffix>"), and the upstream issue filing gate did not recognise such a clone of this repository, so a bare `gh issue create` from it was not gated. Only the ssh-style forms are mapped, and only a suffix of letters, digits, `.`, `-` and `_`: an `https://github.com-<suffix>/...` URL, an enterprise host, and an empty or odd suffix are left as written, so gh still refuses a host it cannot reach. The port refusal and owner/repository checks of the remote route are unchanged.
