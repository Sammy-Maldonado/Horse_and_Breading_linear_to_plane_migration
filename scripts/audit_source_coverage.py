import json
from collections import Counter
from pathlib import Path


# =========================================================
# Load latest Linear backup
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BACKUP_DIR = ROOT_DIR / "backups"

backup_dir = BACKUP_DIR

backups = sorted(
    backup_dir.glob("linear_backup_*.json"),
    key=lambda path: path.stat().st_mtime,
)

if not backups:
    raise RuntimeError("No Linear backup found")

backup_path = backups[-1]

with backup_path.open(
    "r",
    encoding="utf-8",
) as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Fields already covered by the migration
# =========================================================

COVERED_ISSUE_FIELDS = {
    "id",
    "identifier",
    "title",
    "description",
    "state",
    "priority",
    "parent",
    "labels",
    "comments",
    "attachments",
    "relations",
    "inverseRelations",
}

COVERED_COMMENT_FIELDS = {
    "id",
    "body",
    "user",
    "createdAt",
    "updatedAt",
    "resolvedAt",
    "archivedAt",
    "parent",
    "quotedText",
}

COVERED_ATTACHMENT_FIELDS = {
    "id",
    "url",
    "title",
}

COVERED_RELATION_FIELDS = {
    "id",
    "type",
    "issue",
    "relatedIssue",
}


# =========================================================
# Helpers
# =========================================================

def is_nonempty(value):
    if value is None:
        return False

    if value == "":
        return False

    if value == []:
        return False

    if value == {}:
        return False

    return True


def short(value, limit=220):
    text = json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )

    if len(text) > limit:
        return text[:limit] + "..."

    return text


def extract_collection(value):
    if not value:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        for key in (
            "nodes",
            "results",
            "data",
        ):
            result = value.get(key)

            if isinstance(result, list):
                return result

    return []


def audit_records(
    title,
    records,
    covered_fields,
):
    all_fields = set()

    for record in records:
        all_fields.update(
            record.keys()
        )

    print()
    print("========================================")
    print(title)
    print("========================================")
    print()

    review_fields = []

    for field in sorted(all_fields):
        values = [
            record.get(field)
            for record in records
            if is_nonempty(
                record.get(field)
            )
        ]

        nonempty_count = len(values)

        status = (
            "COVERED"
            if field in covered_fields
            else "REVIEW"
        )

        print(
            f"{field:<25} "
            f"{nonempty_count:>5} "
            f"{status}"
        )

        if (
            status == "REVIEW"
            and nonempty_count
        ):
            review_fields.append(
                (
                    field,
                    values,
                )
            )

    if not review_fields:
        print()
        print(
            "No additional non-empty "
            "fields require review."
        )

        return

    print()
    print("----------------------------------------")
    print("FIELDS REQUIRING REVIEW")
    print("----------------------------------------")

    for field, values in review_fields:
        print()
        print(
            f"{field} "
            f"({len(values)} non-empty)"
        )

        # Show up to 3 distinct examples.
        seen = set()
        shown = 0

        for value in values:
            rendered = short(value)

            if rendered in seen:
                continue

            seen.add(rendered)

            print(
                "  example:",
                rendered,
            )

            shown += 1

            if shown >= 3:
                break


# =========================================================
# Build nested collections
# =========================================================

comments = []
attachments = []
relations = []


for issue in issues:
    comments.extend(
        extract_collection(
            issue.get("comments")
        )
    )

    attachments.extend(
        extract_collection(
            issue.get("attachments")
        )
    )

    relations.extend(
        extract_collection(
            issue.get("relations")
        )
    )

    relations.extend(
        extract_collection(
            issue.get("inverseRelations")
        )
    )


# =========================================================
# Summary
# =========================================================

print("========================================")
print("LINEAR SOURCE COVERAGE AUDIT")
print("========================================")
print()

print(
    "Backup:",
    backup_path,
)

print(
    "Issues:",
    len(issues),
)

print(
    "Comments:",
    len(comments),
)

print(
    "Attachments:",
    len(attachments),
)

print(
    "Relation appearances:",
    len(relations),
)


# =========================================================
# Audits
# =========================================================

audit_records(
    "ISSUE FIELDS",
    issues,
    COVERED_ISSUE_FIELDS,
)

audit_records(
    "COMMENT FIELDS",
    comments,
    COVERED_COMMENT_FIELDS,
)

audit_records(
    "ATTACHMENT FIELDS",
    attachments,
    COVERED_ATTACHMENT_FIELDS,
)

audit_records(
    "RELATION FIELDS",
    relations,
    COVERED_RELATION_FIELDS,
)


print()
print("========================================")
print("AUDIT COMPLETE")
print("========================================")
print()

print(
    "No data was modified in Linear or Plane."
)