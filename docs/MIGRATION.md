# Migration Record: Linear → Plane Community

**Completion date:** 2026-10-02
**Target:** Plane Community v1.4.2, self-hosted
**Source scope:** Linear team `HOR`
**Result:** `FINAL MIGRATION AUDIT PASSED`

## 1. Objective

Move the complete operational issue history used by the Horse & Breeder project from Linear into a self-hosted Plane Community project without silent data loss.

The migration was team-scoped rather than project-scoped because the Linear team contained source issues that were not assigned to the named Linear project. The audit found:

- 220 total team issues.
- 189 issues attached to the Linear project.
- 31 team issues with no Linear project assignment.

All 220 were migrated.

## 2. Source inventory

### Issues and workflow

- Issues: **220** (`HOR-1` through `HOR-220`).
- States used by source issues:
  - Backlog: 52
  - Canceled: 2
  - Done: 165
  - In Progress: 1
- Priorities:
  - Urgent: 16
  - High: 100
  - Medium: 62
  - Low: 15
  - No priority: 27

### Hierarchy

- Issues with a parent: **193**.
- Child relationships: **193**.
- Source parent/child representation was symmetric.

### Comments

- Comments: **475**.
- Replies: **3**.
- Issues containing comments: **167**.

### Labels

- Distinct labels: **1**.
- Label: `Improvement`.
- Color: `#4EA7FC`.
- Used by: `HOR-156`.

### Links / attachments

- Attachment rows: **457**.
- Unique URLs: **428**.
- All discovered attachment URLs were GitHub URLs.
- No Linear-hosted binary assets were detected.
- Linear issue documents: **0**.

### Issue relations

The Linear export contained 1,730 relation appearances, corresponding to **865 unique relations**, each represented from both endpoints:

- `blocks`: **29** unique relations.
- `related`: **836** unique relations.
- Unresolved external relation targets: **0**.

### Assignees

- Assigned issues: **155**.
- Unassigned issues: **65**.

### Historical metadata captured

Per-issue source metadata included:

- source branch name: 220
- source URL: 220
- `createdAt`: 220
- `updatedAt`: 220
- `startedAt`: 165
- `completedAt`: 165
- `canceledAt`: 2

The historical sidecar also preserves:

- source issue records: 220
- source comment URLs: 475
- projectless-source flag: 31

## 3. Target preparation

The target Plane project was empty before the base import.

Plane workflow states were mapped as follows:

| Linear | Plane |
| --- | --- |
| Backlog | Backlog |
| Todo | Todo |
| In Progress | In Progress |
| Done | Done |
| Canceled | Cancelled |

Authentication was verified against the Plane API before writes began.

## 4. Preserving HOR-1 through HOR-220

A disposable Plane project was used to test whether the API respected an explicitly supplied `sequence_id`.

It did not. Example behavior observed during testing:

- requested sequence 37 → Plane created sequence 1
- requested sequence 5 → Plane created sequence 2

Therefore exact source numbering could not be restored by directly setting a sequence value.

### Chosen strategy

1. Start with an empty target project.
2. Sort source issues by Linear sequence.
3. Create them strictly in ascending order.
4. Verify every resulting Plane identifier against the Linear identifier.

This produced exact preservation of:

```text
HOR-1 -> HOR-220
```

## 5. Rate limiting and restart behavior

During the base import Plane returned HTTP 429 after a burst of creates.

The migration scripts were adjusted to:

- use a conservative delay between requests;
- retry on HTTP 429;
- respect `Retry-After` when available;
- otherwise wait before retrying;
- reuse local mapping artifacts so completed work could be recognized on rerun.

The first base run created 29 work items before rate limiting. A subsequent run recognized those 29 and created the remaining 191. The target was then verified at exactly 220 items.

## 6. Migration stages

### Stage A — Source export and validation

Relevant scripts:

```text
scripts/export_linear.py
scripts/validate_backup.py
scripts/audit_assets.py
scripts/audit_source_coverage.py
```

Outputs include the source backup and audit inventories under `backups/`.

Key result:

```text
220 issues
475 comments
457 attachment rows
865 unique relations
193 parents
31 projectless issues
```

### Stage B — Target inspection and behavior tests

Relevant scripts:

```text
scripts/inspect_plane.py
scripts/test_plane_sequence.py
scripts/test_plane_relations.py
```

Disposable Plane projects were used for behavior tests. The real target was not used for destructive experiments.

The relation test confirmed:

- creating `blocking` from A to B appears as `blocking` on A and `blocked_by` on B;
- `relates_to` appears symmetrically on both endpoints.

### Stage C — Migration planning

Relevant script:

```text
scripts/prepare_migration.py
```

Dry-run results verified:

- 220 target work items planned;
- exact `HOR-1` through `HOR-220` source sequence;
- source state and priority distributions;
- 193 parent links.

### Stage D — Base work items

Relevant script:

```text
scripts/import_plane_base.py
```

Migrated natively:

- title
- state
- priority
- Linear provenance via `external_source=linear`
- Linear issue UUID via `external_id`

### Stage E — Content and hierarchy

Relevant script:

```text
scripts/import_plane_content.py
```

Verified:

- descriptions: 220
- parent relationships: 193
- exact identifiers unchanged after update

### Stage F — Comments

Relevant script:

```text
scripts/import_plane_comments.py
```

Migrated:

- 475 comments
- Linear comment IDs through Plane external provenance fields
- original author/date metadata embedded visibly in migrated comments
- reply intent from the source mapping

Plane system-level comment creator and timestamps were not falsified. Original source metadata was preserved instead.

### Stage G — Labels

Relevant script:

```text
scripts/import_plane_labels.py
```

Verified:

- label `Improvement`
- color `#4EA7FC`
- assignment to `HOR-156`

### Stage H — GitHub links

Relevant script:

```text
scripts/import_plane_github_links.py
```

Verified:

- source attachment rows: 457
- imported link mappings: 457
- final links: 457

### Stage I — Issue relations

Relevant scripts:

```text
scripts/inspect_linear_relations.py
scripts/import_plane_relations.py
```

Verified:

- 865 unique relations
- 29 `blocks`
- 836 `related`
- Plane relation appearances matched the expected directional/symmetric representation

### Stage J — Assignees and historical metadata

Relevant scripts:

```text
scripts/inspect_remaining_metadata.py
scripts/import_plane_assignees.py
```

Verified:

- 155 assigned
- 65 unassigned

Generated historical sidecar:

```text
backups/linear_historical_metadata.json
```

This preserves metadata that was intentionally not rewritten as target-system history.

## 7. Plane v1.4.2 comment reply limitation

The final audit initially failed on one of the three Linear replies.

Investigation with:

```text
scripts/inspect_comment_replies.py
```

showed that:

- the migrated reply comment existed;
- its mapped parent comment existed;
- both belonged to the correct Plane work item;
- all three migrated replies returned `parent: null` through the Plane API.

This proved a structural loss specific to reply-parent persistence, not missing comment content.

### Controlled repair

Because the target Plane instance was self-hosted and the underlying `IssueComment` model contains a parent relation, a narrow repair was applied with:

```text
scripts/repair_plane_comment_parents.py
```

The repair:

1. Read the three reply relationships from the Linear backup and migration mappings.
2. Resolved each migrated reply and parent by their Plane IDs.
3. Verified `external_source=linear` and matching Linear `external_id` values.
4. Verified reply and parent belonged to the same issue, project, and workspace.
5. Refused to overwrite any unexpected existing parent.
6. Updated only `IssueComment.parent_id` for the three known replies.
7. Re-read the comments through the Plane API.
8. Verified all **3 / 3** reply relationships.

A post-repair database dump was retained locally as:

```text
backups/plane_after_reply_parent_repair.sql
```

Generated database dumps remain git-ignored.

## 8. Whitespace-only description representation

The first final-audit attempt also exposed one description difference on `HOR-211`.

The source and target differed only in whitespace introduced by Markdown/HTML/editor normalization.

The validator was deliberately not relaxed into a generic fuzzy comparison. Its rule is:

1. require exact text first;
2. if exact comparison fails, remove whitespace from both representations;
3. accept only if the remaining content is identical;
4. otherwise fail as a real content mismatch.

Final result:

```text
Whitespace-only description differences: 1
Affected: HOR-211
```

No non-whitespace content mismatch was accepted.

## 9. Final audit

Relevant script:

```text
scripts/final_migration_audit.py
```

Final output:

```text
FINAL MIGRATION AUDIT PASSED

Work items:       220 / 220
Descriptions:     220 / 220
Parents:          193 / 193
Assignees:        155 assigned + 65 unassigned
Comments:         475 / 475
Replies:          3 / 3
GitHub links:     457 / 457
Labels:           1 / 1
Relations:        865 / 865
Historical meta:  220 issues + 475 comment URLs
Projectless:      31 / 31 preserved

Whitespace-only description differences: 1
Affected: HOR-211

HOR-1 -> HOR-220 preserved exactly.
No silent source-data loss detected.
```

Audit artifact:

```text
backups/final_migration_audit.json
```

## 10. Data intentionally not rewritten as native Plane history

The migration does not pretend that Plane created historical Linear records at their original source time.

Instead, it preserves source truth explicitly:

- original comment authors and dates are carried as migration metadata;
- source issue timestamps remain in the historical sidecar when Plane cannot faithfully accept them;
- source comment URLs remain in the historical sidecar;
- source project membership, including 31 projectless issues, is retained as historical metadata.

This keeps target operational data usable without falsifying provenance.

## 11. Generated artifacts

The migration produced local artifacts such as:

```text
backups/linear_backup_<timestamp>.json
backups/linear_asset_inventory.json
backups/plane_migration_plan.json
backups/linear_to_plane_mapping.json
backups/linear_to_plane_comment_mapping.json
backups/linear_to_plane_label_mapping.json
backups/linear_to_plane_link_mapping.json
backups/linear_relation_audit.json
backups/linear_to_plane_relation_mapping.json
backups/linear_historical_metadata.json
backups/final_migration_audit.json
backups/plane_after_reply_parent_repair.sql
```

These are runtime evidence/recovery artifacts and are intentionally excluded from Git.

## 12. Closure criteria

The migration is considered complete only because all of the following are true:

- target issue count is exact;
- source identifiers are preserved exactly;
- migrated data matches source backup and local mappings;
- reply structure is natively present after controlled repair;
- historical metadata that cannot be mapped natively is archived;
- the independent final audit passes;
- no silent source-data loss is detected.
