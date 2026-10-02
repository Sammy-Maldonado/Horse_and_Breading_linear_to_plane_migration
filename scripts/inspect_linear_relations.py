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

with backup_path.open("r", encoding="utf-8") as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Helpers
# =========================================================

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


def summarize_issue(value):
    if not isinstance(value, dict):
        return None

    return {
        "id": value.get("id"),
        "identifier": value.get("identifier"),
        "title": value.get("title"),
    }


# =========================================================
# Collect relation appearances
# =========================================================

appearances = []

unique_relations = {}

type_appearances = Counter()

issues_with_relations = set()


for owner in issues:
    owner_identifier = owner["identifier"]

    for collection_name in (
        "relations",
        "inverseRelations",
    ):
        relations = extract_collection(
            owner.get(collection_name)
        )

        if relations:
            issues_with_relations.add(
                owner_identifier
            )

        for relation in relations:
            relation_id = relation.get("id")

            if not relation_id:
                raise RuntimeError(
                    f"{owner_identifier}: "
                    f"relation without ID"
                )

            relation_type = relation.get(
                "type"
            )

            type_appearances[
                relation_type
            ] += 1

            appearance = {
                "owner": owner_identifier,
                "collection": collection_name,
                "relation_id": relation_id,
                "type": relation_type,
                "issue": summarize_issue(
                    relation.get("issue")
                ),
                "relatedIssue": summarize_issue(
                    relation.get(
                        "relatedIssue"
                    )
                ),
            }

            appearances.append(
                appearance
            )

            if relation_id not in unique_relations:
                unique_relations[
                    relation_id
                ] = {
                    "id": relation_id,
                    "type": relation_type,
                    "appearances": [],
                }

            existing = unique_relations[
                relation_id
            ]

            if (
                existing["type"]
                != relation_type
            ):
                raise RuntimeError(
                    f"Relation {relation_id} "
                    "has inconsistent types: "
                    f"{existing['type']} vs "
                    f"{relation_type}"
                )

            existing[
                "appearances"
            ].append(
                appearance
            )


# =========================================================
# Unique type counts
# =========================================================

unique_type_counts = Counter()

for relation in unique_relations.values():
    unique_type_counts[
        relation["type"]
    ] += 1


# =========================================================
# Appearance counts per unique relation
# =========================================================

appearance_count_distribution = (
    Counter(
        len(
            relation[
                "appearances"
            ]
        )
        for relation in (
            unique_relations.values()
        )
    )
)


# =========================================================
# Detect usable endpoints
# =========================================================

resolved = []
unresolved = []


for relation_id, relation in (
    unique_relations.items()
):
    endpoint_pairs = set()

    for appearance in relation[
        "appearances"
    ]:
        issue = appearance.get(
            "issue"
        )

        related = appearance.get(
            "relatedIssue"
        )

        issue_identifier = (
            issue.get("identifier")
            if issue
            else None
        )

        related_identifier = (
            related.get("identifier")
            if related
            else None
        )

        if (
            issue_identifier
            and related_identifier
        ):
            endpoint_pairs.add(
                (
                    issue_identifier,
                    related_identifier,
                )
            )

    if endpoint_pairs:
        resolved.append(
            {
                "id": relation_id,
                "type": relation["type"],
                "endpoint_pairs": sorted(
                    endpoint_pairs
                ),
                "appearance_count": len(
                    relation["appearances"]
                ),
            }
        )
    else:
        unresolved.append(
            {
                "id": relation_id,
                "type": relation["type"],
                "appearances": relation[
                    "appearances"
                ],
            }
        )


# =========================================================
# Save detailed audit
# =========================================================

output_path = (
    backup_dir
    / "linear_relation_audit.json"
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
            "appearance_count": len(
                appearances
            ),
            "unique_relation_count": len(
                unique_relations
            ),
            "type_appearances": dict(
                type_appearances
            ),
            "unique_type_counts": dict(
                unique_type_counts
            ),
            "appearance_distribution": {
                str(key): value
                for key, value
                in sorted(
                    appearance_count_distribution.items()
                )
            },
            "resolved": resolved,
            "unresolved": unresolved,
        },
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Report
# =========================================================

print("========================================")
print("LINEAR RELATION AUDIT")
print("========================================")
print()

print(
    "Relation appearances:",
    len(appearances),
)

print(
    "Unique relation IDs:",
    len(unique_relations),
)

print(
    "Issues with relations:",
    len(issues_with_relations),
)

print()

print("Appearance types:")

for relation_type, count in sorted(
    type_appearances.items(),
    key=lambda item: str(item[0]),
):
    print(
        f"  {relation_type}: {count}"
    )

print()

print("Unique relation types:")

for relation_type, count in sorted(
    unique_type_counts.items(),
    key=lambda item: str(item[0]),
):
    print(
        f"  {relation_type}: {count}"
    )

print()

print(
    "Appearances per unique relation:"
)

for count, relations_count in sorted(
    appearance_count_distribution.items()
):
    print(
        f"  {count} appearances: "
        f"{relations_count} relations"
    )

print()

print(
    "Relations with explicit "
    "issue + relatedIssue endpoints:",
    len(resolved),
)

print(
    "Relations without explicit "
    "endpoint pair:",
    len(unresolved),
)

print()


# =========================================================
# Show representative raw samples
# =========================================================

print("========================================")
print("RAW SAMPLES")
print("========================================")

shown_types = set()

for appearance in appearances:
    relation_type = appearance[
        "type"
    ]

    if relation_type in shown_types:
        continue

    shown_types.add(
        relation_type
    )

    print()
    print(
        "TYPE:",
        relation_type,
    )

    print(
        json.dumps(
            appearance,
            ensure_ascii=False,
            indent=2,
        )
    )

    if len(shown_types) >= 10:
        break


print()
print("========================================")
print("AUDIT COMPLETE")
print("========================================")

print(
    "Output:",
    output_path,
)

print()
print(
    "No data was written to Plane."
)