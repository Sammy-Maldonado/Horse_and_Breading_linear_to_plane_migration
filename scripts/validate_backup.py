import json
import re
from collections import Counter
from pathlib import Path


# =========================================================
# Find newest backup automatically
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

print("Validating:", backup_path)
print()


# =========================================================
# Load JSON
# =========================================================

with backup_path.open("r", encoding="utf-8") as file:
    backup = json.load(file)

issues = backup.get("issues", [])


# =========================================================
# Basic issue validation
# =========================================================

errors = []
warnings = []

if len(issues) != 220:
    errors.append(
        f"Expected 220 issues, found {len(issues)}"
    )


identifiers = [
    issue.get("identifier")
    for issue in issues
]

uuids = [
    issue.get("id")
    for issue in issues
]


if len(set(identifiers)) != len(identifiers):
    errors.append("Duplicate HOR identifiers found")

if len(set(uuids)) != len(uuids):
    errors.append("Duplicate Linear issue UUIDs found")


def issue_number(identifier):
    return int(identifier.split("-")[1])


numbers = sorted(
    issue_number(identifier)
    for identifier in identifiers
)

expected_numbers = list(range(1, 221))

if numbers != expected_numbers:
    missing = sorted(
        set(expected_numbers) - set(numbers)
    )

    unexpected = sorted(
        set(numbers) - set(expected_numbers)
    )

    errors.append(
        f"HOR sequence invalid. "
        f"Missing={missing}, unexpected={unexpected}"
    )


# =========================================================
# Lookup tables
# =========================================================

by_uuid = {
    issue["id"]: issue
    for issue in issues
}

by_identifier = {
    issue["identifier"]: issue
    for issue in issues
}


# =========================================================
# Parent / child validation
# =========================================================

parent_count = 0
child_count = 0

parent_pairs = set()
child_pairs = set()


for issue in issues:
    parent = issue.get("parent")

    if parent:
        parent_count += 1

        parent_id = parent.get("id")

        if parent_id not in by_uuid:
            errors.append(
                f"{issue['identifier']} references "
                f"unknown parent UUID {parent_id}"
            )
        else:
            parent_pairs.add(
                (
                    parent_id,
                    issue["id"],
                )
            )

    children = (
        issue.get("children", {})
        .get("nodes", [])
    )

    for child in children:
        child_count += 1

        child_id = child.get("id")

        if child_id not in by_uuid:
            errors.append(
                f"{issue['identifier']} references "
                f"unknown child UUID {child_id}"
            )
        else:
            child_pairs.add(
                (
                    issue["id"],
                    child_id,
                )
            )


if parent_pairs != child_pairs:
    missing_from_children = (
        parent_pairs - child_pairs
    )

    missing_from_parents = (
        child_pairs - parent_pairs
    )

    if missing_from_children:
        errors.append(
            "Parent relationships missing from children side: "
            f"{len(missing_from_children)}"
        )

    if missing_from_parents:
        errors.append(
            "Child relationships missing from parent side: "
            f"{len(missing_from_parents)}"
        )


# =========================================================
# Comments
# =========================================================

comment_ids = set()
comment_count = 0
comment_reply_count = 0


for issue in issues:
    for comment in issue.get("comments", []):
        comment_count += 1

        comment_id = comment.get("id")

        if not comment_id:
            errors.append(
                f"{issue['identifier']} has comment without ID"
            )
            continue

        if comment_id in comment_ids:
            errors.append(
                f"Duplicate comment ID: {comment_id}"
            )

        comment_ids.add(comment_id)

        if comment.get("parent"):
            comment_reply_count += 1


# =========================================================
# Attachments
# =========================================================

attachment_ids = set()
attachment_count = 0


for issue in issues:
    attachments = (
        issue.get("attachments", {})
        .get("nodes", [])
    )

    for attachment in attachments:
        attachment_count += 1

        attachment_id = attachment.get("id")

        if attachment_id:
            attachment_ids.add(
                attachment_id
            )

        if not attachment.get("url"):
            warnings.append(
                f"{issue['identifier']} has attachment "
                "without URL"
            )


# =========================================================
# Relations
# =========================================================

relation_ids = set()
relation_types = Counter()
external_relation_targets = set()


for issue in issues:
    connections = []

    connections.extend(
        issue.get("relations", {})
        .get("nodes", [])
    )

    connections.extend(
        issue.get("inverseRelations", {})
        .get("nodes", [])
    )

    for relation in connections:
        relation_id = relation.get("id")

        if relation_id:
            relation_ids.add(relation_id)

        relation_type = relation.get("type")

        if relation_type:
            relation_types[relation_type] += 1

        for field in ("issue", "relatedIssue"):
            target = relation.get(field)

            if not target:
                continue

            target_id = target.get("id")

            if (
                target_id
                and target_id not in by_uuid
            ):
                external_relation_targets.add(
                    (
                        target.get("identifier"),
                        target_id,
                    )
                )


# =========================================================
# Statuses / priorities / labels
# =========================================================

statuses = Counter()
priorities = Counter()
labels = Counter()

projectless = 0


for issue in issues:
    state = issue.get("state")

    if state:
        statuses[state.get("name")] += 1
    else:
        warnings.append(
            f"{issue['identifier']} has no state"
        )

    priorities[
        issue.get("priorityLabel") or "No priority"
    ] += 1

    for label in (
        issue.get("labels", {})
        .get("nodes", [])
    ):
        labels[label.get("name")] += 1

    if issue.get("project") is None:
        projectless += 1


# =========================================================
# Inventory embedded Linear assets
# =========================================================

LINEAR_ASSET_PATTERN = re.compile(
    r'https://[^\s<>"\')]+'
)

embedded_linear_urls = set()


def inspect_text(text):
    if not text:
        return

    for url in LINEAR_ASSET_PATTERN.findall(text):
        lowered = url.lower()

        if (
            "linear.app" in lowered
            or "linearusercontent" in lowered
            or "uploads.linear" in lowered
        ):
            embedded_linear_urls.add(url)


for issue in issues:
    inspect_text(
        issue.get("description")
    )

    for comment in issue.get("comments", []):
        inspect_text(
            comment.get("body")
        )

    for document in (
        issue.get("documents", {})
        .get("nodes", [])
    ):
        inspect_text(
            document.get("content")
        )


# =========================================================
# Metadata check
# =========================================================

metadata_count = (
    backup.get("metadata", {})
    .get("issue_count")
)

if metadata_count != len(issues):
    errors.append(
        f"Metadata says {metadata_count} issues, "
        f"JSON contains {len(issues)}"
    )


# =========================================================
# Final report
# =========================================================

print("========================================")
print("BACKUP VALIDATION")
print("========================================")

print("Issues:", len(issues))
print("First:", min(numbers))
print("Last:", max(numbers))

print()

print("Comments:", comment_count)
print("Comment replies:", comment_reply_count)

print()

print("Attachments:", attachment_count)
print("Unique attachment IDs:", len(attachment_ids))

print()

print("Issues with parent:", parent_count)
print("Child relationships:", child_count)
print(
    "Parent/child pairs:",
    len(parent_pairs),
)

print()

print(
    "Unique issue relations:",
    len(relation_ids),
)

print(
    "External relation targets:",
    len(external_relation_targets),
)

print()

print(
    "Issues without Linear project:",
    projectless,
)

print()

print("Statuses:")

for name, count in sorted(
    statuses.items()
):
    print(f"  {name}: {count}")

print()

print("Priorities:")

for name, count in sorted(
    priorities.items()
):
    print(f"  {name}: {count}")

print()

print(
    "Distinct labels:",
    len(labels),
)

print(
    "Embedded Linear URLs found:",
    len(embedded_linear_urls),
)


if relation_types:
    print()
    print("Relation types:")

    for relation_type, count in sorted(
        relation_types.items()
    ):
        print(
            f"  {relation_type}: {count}"
        )


print()
print("========================================")

if errors:
    print("VALIDATION FAILED")
    print("========================================")

    for error in errors:
        print("ERROR:", error)

    raise SystemExit(1)

else:
    print("STRUCTURAL VALIDATION PASSED")


if warnings:
    print()
    print(
        f"Warnings: {len(warnings)}"
    )

    for warning in warnings[:20]:
        print("WARNING:", warning)

    if len(warnings) > 20:
        print(
            f"... and {len(warnings) - 20} more"
        )


if external_relation_targets:
    print()
    print(
        "External relation targets detected:"
    )

    for identifier, uuid in sorted(
        external_relation_targets
    ):
        print(
            f"  {identifier} | {uuid}"
        )


print()
print(
    "Plane remains untouched."
)