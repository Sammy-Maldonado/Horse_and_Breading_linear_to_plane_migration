# Linear to Plane Migration Toolkit

A validated migration toolkit for moving a Linear team into a self-hosted Plane Community instance while preserving operational history, relationships, provenance, and issue identifiers as faithfully as the target platform allows.

This repository was built around a real migration completed on **2026-10-02** from Linear to **Plane Community v1.4.2**.

## Migration result

The final audit passed with no silent source-data loss detected:

| Data | Verified |
| --- | ---: |
| Work items | 220 / 220 |
| Descriptions | 220 / 220 |
| Parent relationships | 193 / 193 |
| Assignees | 155 assigned + 65 unassigned |
| Comments | 475 / 475 |
| Comment replies | 3 / 3 |
| GitHub links | 457 / 457 |
| Labels | 1 / 1 |
| Unique relations | 865 / 865 |
| Historical issue records | 220 |
| Historical comment URLs | 475 |
| Projectless source issues | 31 / 31 |

The source identifiers **HOR-1 through HOR-220** were preserved exactly.

One description (`HOR-211`) had a whitespace-only representation difference after passing through Plane's editor/API. The final audit accepts that case only after proving that removing whitespace produces identical content.

## What this toolkit preserves

- Linear issue identifiers and ordering.
- Titles, descriptions, states, and priorities.
- Parent/child hierarchy.
- Assignee state.
- Comments and reply relationships.
- GitHub attachment/link records.
- Labels.
- `blocks` and `related` issue relations.
- Linear IDs through `external_source` / `external_id` mappings.
- Source metadata that Plane cannot represent natively, stored in sidecar audit artifacts.

## Important target-platform limitations

The migration intentionally distinguishes between data that Plane can represent natively and source history that must be preserved as metadata.

### Comment authors and source timestamps

Plane creates migrated comments under the migration account and uses target-system timestamps. Original Linear author and timestamp metadata are preserved inside the migrated comment metadata and in the historical sidecar instead of pretending Plane created those records at their original time.

### Comment replies on Plane Community v1.4.2

Plane's underlying comment model supports a parent comment, but the v1 comment creation API used by this migration did not persist the supplied parent relationship. The three Linear replies were therefore created as normal comments first, then repaired through a narrow, validated Django ORM operation against the self-hosted Plane instance.

The repair touched only the three verified reply-to-parent foreign keys and was re-checked through the Plane API before the final audit.

### Source timestamps and other historical fields

Fields that cannot be faithfully assigned as Plane system metadata are retained in `backups/linear_historical_metadata.json` rather than silently discarded.

## Why exact HOR numbering required ordered creation

Plane Community v1.4.2 ignored an explicitly supplied `sequence_id` during testing. To preserve `HOR-1` through `HOR-220`, the target project was kept empty and source issues were created in ascending Linear sequence order.

A disposable Plane project was used to prove this behavior before the real import.

## Project structure

```text
linear-to-plane-migration/
├── backups/                  # Generated backups, mappings and audit outputs; git-ignored
├── docs/
│   ├── MIGRATION.md
│   └── PUBLISH_CHECKLIST.md
├── scripts/
│   ├── audit_assets.py
│   ├── audit_source_coverage.py
│   ├── export_linear.py
│   ├── final_migration_audit.py
│   ├── import_plane_assignees.py
│   ├── import_plane_base.py
│   ├── import_plane_comments.py
│   ├── import_plane_content.py
│   ├── import_plane_github_links.py
│   ├── import_plane_labels.py
│   ├── import_plane_relations.py
│   ├── inspect_comment_replies.py
│   ├── inspect_linear_relations.py
│   ├── inspect_plane.py
│   ├── inspect_remaining_metadata.py
│   ├── migrate.py
│   ├── prepare_migration.py
│   ├── repair_plane_comment_parents.py
│   ├── test_plane_relations.py
│   ├── test_plane_sequence.py
│   └── validate_backup.py
├── .env                      # Local secrets; never commit
├── .env.example
├── .gitignore
└── requirements.txt
```

All scripts resolve `.env` and `backups/` from the project root using `Path(__file__)`, so they do not depend on the terminal's current working directory.

## Requirements

- Python 3
- A Linear API key with access to the source team.
- A self-hosted Plane instance with API access.
- Docker access only for the optional Plane v1.4.2 reply-parent repair.

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

On PowerShell:

```powershell
Copy-Item .env.example .env
```

Then provide your own values:

```env
PLANE_BASE_URL=http://localhost:8080
PLANE_WORKSPACE_SLUG=your-workspace
PLANE_PROJECT_ID=your-project-id
PLANE_API_KEY=

LINEAR_API_KEY=
LINEAR_TEAM_ID=
LINEAR_PROJECT_ID=
```

Never commit `.env`, API keys, generated migration backups, database dumps, or identity-specific local configuration.

## Migration workflow

The migration was executed as explicit stages instead of one opaque operation:

1. Export and validate the Linear source.
2. Audit attachments/assets and source coverage.
3. Inspect the empty Plane target and state mapping.
4. Prove Plane sequence behavior in a disposable project.
5. Generate the migration plan and dry-run mappings.
6. Import base work items in ascending source sequence.
7. Import descriptions and hierarchy.
8. Import comments and comment metadata.
9. Import labels.
10. Import GitHub links.
11. Audit Linear relations and prove Plane relation semantics in a disposable project.
12. Import issue relations.
13. Audit remaining source metadata.
14. Import assignees and archive non-native historical metadata.
15. Inspect and, when required by Plane v1.4.2, repair comment reply parents.
16. Run the final end-to-end audit.

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the detailed record and validation rules.

## Safety principles

This migration follows a few strict rules:

- Back up first.
- Never silently drop source data.
- Preserve provenance when the target cannot represent a source field natively.
- Prove target API behavior with disposable tests before relying on it.
- Keep generated mappings so interrupted stages can be inspected and resumed safely.
- Treat a migration as incomplete until an independent final audit passes.

## Final audit

The final validator compares the migrated Plane project against the Linear backup and local mapping artifacts. It checks counts and per-record identity for work items, descriptions, hierarchy, assignees, comments, replies, GitHub links, labels, relations, and historical metadata.

A successful run ends with:

```text
FINAL MIGRATION AUDIT PASSED
...
HOR-1 -> HOR-220 preserved exactly.
No silent source-data loss detected.
```

The generated audit report is written to:

```text
backups/final_migration_audit.json
```

## Public-repository note

Before publishing, complete the checks in [`docs/PUBLISH_CHECKLIST.md`](docs/PUBLISH_CHECKLIST.md). In particular, remove any hardcoded personal identity used by the original assignee migration and verify that no secrets, local database dumps, or generated migration artifacts are tracked by Git.
