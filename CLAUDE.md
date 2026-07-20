# CLAUDE.md

Guidance for working in this repository.

## Documentation policy

`docs/` documents the real, current implementation — see [docs/README.md](docs/README.md) for the master index. Treat it as part of the codebase, not an afterthought:

1. When a code change affects behavior described in `docs/`, update every relevant reference file in the same session — including that file's card in [docs/FILE_REFERENCE.md](docs/FILE_REFERENCE.md) (Purpose/Responsibilities/Functions/Depends on/Depended on by/Future modification notes) and the affected diagram(s) in [docs/DIAGRAMS.md](docs/DIAGRAMS.md) if imports, routes, or the schema changed.
2. Add a dated entry to [docs/CHANGELOG.md](docs/CHANGELOG.md) using its required template — **Feature, Files changed, Why, Database changes, UI changes, Future impact** — all six fields, "None" where not applicable. Do not write a one-line changelog entry; use the full template.
3. If the change reflects a deliberate architectural choice (not just a bug fix), add an entry to [docs/DECISIONS.md](docs/DECISIONS.md).
4. If the change introduces or surfaces a new inconsistency/gap/shortcut, add a new `TD-N` row to the Known Technical Debt log in [docs/11_FUTURE_WORK.md](docs/11_FUTURE_WORK.md) immediately — this is a living log, not a one-time audit. If the change fixes an existing `TD-N`/`PF-N`, flip its `Status` to `Resolved` (don't delete the row) and reference the changelog entry that fixed it.
5. If the change affects where a common feature lives, update [docs/WHERE_TO_MODIFY.md](docs/WHERE_TO_MODIFY.md) and, if it changes a common failure mode, [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

Do not let `docs/` drift into describing a theoretical or aspirational version of the project — every claim in it should be verifiable by reading the actual source.
