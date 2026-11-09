# Callout: the project-root write guard follows a cd into loop, if, group and subshell bodies

**Plan**: 00587
**Audience**: client projects

(GitHub #195.) `project_containment` (R-WRITE-OUTSIDE-PROJECT-ROOT) judged a relative redirect inside a `for`, `while`/`until`, `if` or `( )` body from the starting directory as well as the directory a preceding `cd ... &&` reached, so `cd sub && for x in a; do echo hi 2>>../f; done` was denied with a target joined to the repository root. The body is now read from the directory the `&&` chain reached, as a top-level step is. A `cd` outside the project, a target that climbs out of the root, a `cd` inside the body and a target before the `cd` stay denied. Only this guard changed; the git gates read the command as before.
