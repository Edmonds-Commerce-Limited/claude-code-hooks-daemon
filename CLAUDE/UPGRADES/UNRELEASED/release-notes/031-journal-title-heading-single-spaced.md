# Callout: a titled journal heading is single-spaced, so formatters leave it alone

**Plan**: 00594
**Audience**: client projects

`mkplan.bash --journal ... --title T` used to put three spaces before the
title (`## HH:MM · category · REF   — T`). A markdown formatter in the
project's own format check (prettier, for example) collapses that run of
spaces. The commit gate treats a journal entry as immutable, so the
collapsed version could never be committed and the format check stayed red.
The scaffolder now writes `## HH:MM · category · REF — T`, which is already
in collapsed form. Existing entries are not touched.

If your format check covers plan files, also exclude `**/JOURNAL/**` from
it. Journal entries are append-only, and the daemon's own markdown
formatter already skips them.
