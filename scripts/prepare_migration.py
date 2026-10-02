import json
from collections import Counter
from pathlib import Path


# =========================================================
# Load newest backup
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

with backup_path.open("r", encoding="utf-8") as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Mapping rules
# =========================================================

STATE_MAP = {
    "Backlog": "Backlog",
    "Todo": "Todo",
    "In Progress": "In Progress",
    "Done": "Done",
    "Canceled": "Cancelled",
}

PRIORITY_MAP = {
    0: "none",
    1: "urgent",
    2: "high",
    3: "medium",
    4: "low",
}


# =========================================================
# Validation / transformation
# =========================================================

errors = []
prepared = []

state_counts = Counter()
priority_counts = Counter()

known_identifiers = {
    issue["identifier"]
    for issue in issues
}


def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


issues.sort(key=issue_number)


for expected_number, issue in enumerate(
    issues,
    start=1,
):
    identifier = issue["identifier"]

    actual_number = issue_number(issue)

    if actual_number != expected_number:
        errors.append(
            f"Expected HOR-{expected_number}, "
            f"found {identifier}"
        )

    linear_state = (
        issue.get("state") or {}
    ).get("name")

    if linear_state not in STATE_MAP:
        errors.append(
            f"{identifier}: unknown state "
            f"{linear_state!r}"
        )

        plane_state = None
    else:
        plane_state = STATE_MAP[linear_state]

    priority_value = issue.get("priority", 0)

    if priority_value not in PRIORITY_MAP:
        errors.append(
            f"{identifier}: unknown priority "
            f"{priority_value!r}"
        )

        plane_priority = None
    else:
        plane_priority = PRIORITY_MAP[
            priority_value
        ]

    parent = issue.get("parent")

    parent_identifier = None

    if parent:
        parent_identifier = parent.get(
            "identifier"
        )

        if (
            parent_identifier
            not in known_identifiers
        ):
            errors.append(
                f"{identifier}: parent "
                f"{parent_identifier} "
                "not present in backup"
            )

    labels = [
        label["name"]
        for label in (
            issue.get("labels", {})
            .get("nodes", [])
        )
    ]

    state_counts[plane_state] += 1
    priority_counts[plane_priority] += 1

    prepared.append(
        {
            "expected_sequence_id": (
                expected_number
            ),
            "linear_identifier": identifier,
            "linear_uuid": issue["id"],
            "name": issue["title"],
            "description": (
                issue.get("description")
                or ""
            ),
            "state": plane_state,
            "priority": plane_priority,
            "parent_identifier": (
                parent_identifier
            ),
            "labels": labels,
            "external_source": "linear",
            "external_id": issue["id"],
        }
    )


# =========================================================
# Save prepared migration
# =========================================================

output_path = (
    backup_dir
    / "plane_migration_plan.json"
)

with output_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        {
            "source_backup": str(
                backup_path
            ),
            "issue_count": len(prepared),
            "issues": prepared,
        },
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Report
# =========================================================

print("========================================")
print("PLANE MIGRATION DRY RUN")
print("========================================")

print("Issues:", len(prepared))

print(
    "First:",
    prepared[0]["linear_identifier"],
)

print(
    "Last:",
    prepared[-1]["linear_identifier"],
)

print()

print("States:")

for state, count in sorted(
    state_counts.items()
):
    print(
        f"  {state}: {count}"
    )

print()

print("Priorities:")

for priority, count in sorted(
    priority_counts.items()
):
    print(
        f"  {priority}: {count}"
    )

print()

print(
    "Parent relationships:",
    sum(
        1
        for item in prepared
        if item["parent_identifier"]
    ),
)

print()

print(
    "Migration plan:",
    output_path,
)

print()

if errors:
    print("DRY RUN FAILED")
    print()

    for error in errors:
        print("ERROR:", error)

    raise SystemExit(1)

print("DRY RUN PASSED")
print("No data was written to Plane.")