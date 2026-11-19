# Plan 00623: final adversarial review (tip 761a450e1)

Status: INTERIM. Being filled in; the escapes below are confirmed in real bash.

## Real-bash escapes found so far

The branch secret guard ALLOWS each of these, and bash prints the dummy protected content. Fixture: 20 holding directories (`wNN/.bin/tool` links inside the project), plus `w19/zz/late` linking to a dummy protected file outside it. Tools: `review2-tools/`.

| Command                                                                          | Branch modes that allow it          | Main   |
| -------------------------------------------------------------------------------- | ----------------------------------- | ------ |
| `cat w19/zz/[l]ate` (static, no `cd`)                                            | all                                 | allows |
| `cd w19 && cat zz/[l]ate`                                                        | all                                 | allows |
| `ln -s w19/zz n && cat n/late`                                                   | all                                 | allows |
| `cd "$D" && cat zz/[l]ate`, `zz/la[t]e`, `zz/l[a-z]te`, `z[z]/late`              | under the cap (the shipped default) | allows |
| `cd "$D" && cat .bin/../zz/late`, `.bin/./../zz/late`                            | under the cap                       | allows |
| `cd "$D" && cat zz/${X:-late}`, `zz/${X-late}`, `zz/${X:=late}`, `${D:+zz/late}` | under the cap                       | allows |
| `cd "$D" && cat zz/+(l)ate`, `zz/!(x)` (extglob on)                              | all                                 | allows |

DENY-on-main to ALLOW-on-branch: 0 (main allows every one of these too, so they are not regressions against main).
