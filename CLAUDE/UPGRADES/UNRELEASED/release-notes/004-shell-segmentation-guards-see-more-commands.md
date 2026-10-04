# Callout: three shell shapes that slipped past a guard are now judged

**Plan**: 00483
**Audience**: everyone

Three ordinary command shapes were allowed when they should not have been. `sed_blocker` now treats a newline as ending a `git commit`, so `git commit -m x` followed on the next line by a `sed` command is denied, and every `sed` must sit inside the commit command to be exempt. A `$'...'` word handed to a shell (`bash -c $'echo a\ngit reset --hard'`) is decoded before it is judged, so the commands its `\n` separates are each seen. `project_containment` judges the literal body of an `eval` as it judges a `bash -c` body, so `eval 'echo x > /opt/zz.txt'` is denied as a write outside the project. A `;` inside a quoted commit message no longer defeats the `sed` exemption. `eval "$VAR"` is still not judged, because its text is not visible.
