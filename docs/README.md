# Documentation Index — Smart Library App

This `docs/` folder documents the **actual, current implementation** of the Smart Library App codebase — not aspirational or theoretical software-engineering artifacts. Every claim in it should be verifiable by reading the corresponding source file(s) it cites.

## Master index

**Start here**
| File | Contents |
|---|---|
| [01_OVERVIEW.md](01_OVERVIEW.md) | What the app does, tech stack, how to run it locally, multi-tenant model, feature status table |
| [02_ARCHITECTURE.md](02_ARCHITECTURE.md) | App bootstrap, request lifecycle, session/auth model, config, cross-cutting patterns |
| [CODE_JOURNEY.md](CODE_JOURNEY.md) | Two full request walkthroughs (a write flow, a read flow) traced file-by-file, plus the general pattern for adding a new feature |

**Visual reference**
| File | Contents |
|---|---|
| [DIAGRAMS.md](DIAGRAMS.md) | 5 Mermaid diagrams: folder structure, layered architecture, request-flow sequence, database ER diagram, literal module-import graph |

**Structural reference (what exists, and its purpose)**
| File | Contents |
|---|---|
| [03_PROJECT_STRUCTURE.md](03_PROJECT_STRUCTURE.md) | Annotated file/folder tree — one-line purpose for every file |
| [FILE_REFERENCE.md](FILE_REFERENCE.md) | Per-file deep-dive cards (Purpose, Responsibilities, Functions/Classes, Depends on, Depended on by, Future modification notes) for `app.py`, every route, every database module, every template folder, and `utils/charts.py` |
| [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) | Every table, column, relationship, and migration script, with known inconsistencies flagged |
| [05_ROUTES_REFERENCE.md](05_ROUTES_REFERENCE.md) | Every blueprint and route: method, path, template, auth check, purpose |
| [06_TEMPLATES_REFERENCE.md](06_TEMPLATES_REFERENCE.md) | Layout system, every template and component, context variables expected |
| [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md) | CSS/JS/chart images/uploads — what each file does |
| [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) | `utils/charts.py` in detail, plus what the empty `models/`, `services/`, `reports/`, `tests/`, `backups/`, `.agents/` folders were apparently meant to hold |
| [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) | Text form of the module dependency graph, plus cross-blueprint `url_for` couplings (runtime-only, not imports) |
| [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md) | End-to-end walkthrough per feature (route → query → template) |

**Task-oriented guides**
| File | Contents |
|---|---|
| [WHERE_TO_MODIFY.md](WHERE_TO_MODIFY.md) | "I want to change X" → every file that touches it, in one table |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues specific to this codebase, their root cause, and the fix |

**Living project history**
| File | Contents |
|---|---|
| [11_FUTURE_WORK.md](11_FUTURE_WORK.md) | Known Technical Debt log (`TD-1`…`TD-21`, with severity/location/status), Stub Routes & Planned Features (`PF-1`…), and recommended next slices |
| [CHANGELOG.md](CHANGELOG.md) | Dated entries — Feature / Files changed / Why / Database changes / UI changes / Future impact |
| [DECISIONS.md](DECISIONS.md) | Architecture decisions (ADR-1…ADR-6) and the reasoning behind them |
| [MIRROR_TRACKER.md](MIRROR_TRACKER.md) | Per-table tracker for the incremental Supabase migration — source of truth, current SQLite mirror readers/writers, exact removal conditions, and status for `admins`/`enquiries`/`students`/`memberships`; update after every migration slice until the final SQLite removal |

## Maintenance policy (mandatory, not optional)

**Documentation is part of the codebase.** Whenever code changes in a way that affects behavior described here:

1. Update every reference file above that the change touches, in the same session — not "later." If you changed a route, update [05_ROUTES_REFERENCE.md](05_ROUTES_REFERENCE.md) and that route's card in [FILE_REFERENCE.md](FILE_REFERENCE.md); if you changed the schema, update [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) and the ER diagram in [DIAGRAMS.md](DIAGRAMS.md); if you added or removed an import, update both ends of that edge in [FILE_REFERENCE.md](FILE_REFERENCE.md) and the graph in [DIAGRAMS.md](DIAGRAMS.md).
2. Add a dated entry to [CHANGELOG.md](CHANGELOG.md) using its required template (Feature / Files changed / Why / Database changes / UI changes / Future impact) — all six fields, even if a field is "None."
3. If the change reflects a deliberate architectural choice (not just a bug fix), add an entry to [DECISIONS.md](DECISIONS.md).
4. If the change surfaces a new inconsistency, gap, or shortcut you didn't have time to fix, add a new `TD-N` row to the [11_FUTURE_WORK.md](11_FUTURE_WORK.md) technical-debt log immediately — don't let it go unrecorded. If a change fixes an existing `TD-N`/`PF-N`, flip its status instead of deleting the row, and reference the fixing changelog entry.

This policy is also recorded in the project's `CLAUDE.md` so it's applied automatically in future coding sessions — treat drift between `docs/` and the actual source as a bug in its own right.

## History

This documentation system replaced a set of 20 generic, template-style planning documents (`01_Requirement_Analysis.md` through `20_Normalization.md`) written before most of the current codebase existed and never updated afterward — they described a theoretical project (referencing a non-existent `ml/` folder, MySQL, Scikit-learn, ReportLab, etc.) with no relationship to the real Flask/SQLite implementation. They were removed once this reference set was verified against the actual source (see the 2026-07-20 entries in [CHANGELOG.md](CHANGELOG.md) for both the initial replacement and the subsequent expansion into per-file cards, diagrams, and the technical-debt log).
