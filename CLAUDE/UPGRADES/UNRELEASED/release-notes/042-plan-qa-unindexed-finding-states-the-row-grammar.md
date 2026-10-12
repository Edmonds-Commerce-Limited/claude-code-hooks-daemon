# Callout: plan QA's "no README index row" finding states the accepted row forms

**Plan**: 00474
**Audience**: everyone

The plan index reader only accepts top-level bullet rows, so a markdown table row such as `| [00001](00001-x/PLAN.md) | Title | Not Started |` was silently ignored and every plan was reported as having no README index row, with a remediation that named no grammar. The `row-folder-bijection` finding now states both accepted forms (`- [NNNNN: Title](NNNNN-name/PLAN.md) - status` and `- **NNNNN** - status`, under a `##` section heading), and when the README holds a table row for the plan it says so and that table rows are not read as index rows. Table rows still do not satisfy the check, and the finding's level is unchanged.
