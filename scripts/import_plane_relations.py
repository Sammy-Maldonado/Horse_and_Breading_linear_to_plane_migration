import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================================================
# Configuration
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BACKUP_DIR = ROOT_DIR / "backups"

load_dotenv(ROOT_DIR / ".env")

PLANE_BASE_URL = os.getenv("PLANE_BASE_URL")
PLANE_WORKSPACE_SLUG = os.getenv("PLANE_WORKSPACE_SLUG")
PLANE_PROJECT_ID = os.getenv("PLANE_PROJECT_ID")
PLANE_API_KEY = os.getenv("PLANE_API_KEY")

if not all([
    PLANE_BASE_URL,
    PLANE_WORKSPACE_SLUG,
    PLANE_PROJECT_ID,
    PLANE_API_KEY,
]):
    raise RuntimeError("Missing Plane environment variables")


HEADERS = {
    "X-API-Key": PLANE_API_KEY,
    "Content-Type": "application/json",
}

REQUEST_DELAY_SECONDS = 1.2
MAX_RATE_LIMIT_RETRIES = 10


# =========================================================
# HTTP helper
# =========================================================

def request(method, path, **kwargs):
    url = f"{PLANE_BASE_URL}{path}"

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        response = requests.request(
            method,
            url,
            headers=HEADERS,
            timeout=60,
            **kwargs,
        )

        if response.status_code == 429:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                print()
                print("Rate limit retry limit reached.")
                print(response.text)
                response.raise_for_status()

            retry_after = response.headers.get(
                "Retry-After"
            )

            try:
                wait_seconds = float(
                    retry_after
                )
            except (TypeError, ValueError):
                wait_seconds = 65

            print()
            print(
                f"Plane rate limit reached. "
                f"Waiting {wait_seconds:.0f} seconds..."
            )

            time.sleep(wait_seconds)
            continue

        time.sleep(REQUEST_DELAY_SECONDS)

        if not response.ok:
            print()
            print("Plane API error")
            print(method, path)
            print("Status:", response.status_code)
            print(response.text)
            print()

            response.raise_for_status()

        if response.status_code == 204:
            return None

        return response.json()

    raise RuntimeError(
        "Unexpected Plane API retry failure"
    )


# =========================================================
# Load latest Linear backup
# =========================================================

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
# Load Linear -> Plane work-item mapping
# =========================================================

work_mapping_path = (
    backup_dir
    / "linear_to_plane_mapping.json"
)

if not work_mapping_path.exists():
    raise RuntimeError(
        "linear_to_plane_mapping.json not found"
    )

with work_mapping_path.open(
    "r",
    encoding="utf-8",
) as file:
    work_mapping = json.load(file)

if len(work_mapping) != 220:
    raise RuntimeError(
        f"Expected 220 work-item mappings, "
        f"found {len(work_mapping)}"
    )


# =========================================================
# Relation migration mapping
# =========================================================

relation_mapping_path = (
    backup_dir
    / "linear_to_plane_relation_mapping.json"
)

if relation_mapping_path.exists():
    with relation_mapping_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        relation_mapping = json.load(file)
else:
    relation_mapping = {}


def save_relation_mapping():
    with relation_mapping_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            relation_mapping,
            file,
            ensure_ascii=False,
            indent=2,
        )


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


def issue_number(identifier):
    return int(
        identifier.split("-")[1]
    )


def relations_path(plane_work_item_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_work_item_id}/relations/"
    )


# =========================================================
# Build unique Linear relation inventory
# =========================================================

unique_relations = {}

appearance_count = 0


for owner in issues:
    owner_identifier = owner["identifier"]

    for collection_name in (
        "relations",
        "inverseRelations",
    ):
        relations = extract_collection(
            owner.get(collection_name)
        )

        for relation in relations:
            appearance_count += 1

            relation_id = relation.get("id")
            relation_type = relation.get("type")

            source = (
                relation.get("issue")
                or {}
            ).get("identifier")

            target = (
                relation.get("relatedIssue")
                or {}
            ).get("identifier")

            if not relation_id:
                raise RuntimeError(
                    f"{owner_identifier}: "
                    "relation without ID"
                )

            if relation_type not in {
                "blocks",
                "related",
            }:
                raise RuntimeError(
                    f"{relation_id}: unexpected "
                    f"relation type {relation_type!r}"
                )

            if not source or not target:
                raise RuntimeError(
                    f"{relation_id}: missing "
                    "source/target"
                )

            if source == target:
                raise RuntimeError(
                    f"{relation_id}: self relation "
                    f"on {source}"
                )

            signature = (
                relation_type,
                source,
                target,
            )

            if relation_id not in unique_relations:
                unique_relations[
                    relation_id
                ] = {
                    "id": relation_id,
                    "type": relation_type,
                    "source": source,
                    "target": target,
                    "appearances": 1,
                }

            else:
                existing = unique_relations[
                    relation_id
                ]

                existing_signature = (
                    existing["type"],
                    existing["source"],
                    existing["target"],
                )

                if existing_signature != signature:
                    raise RuntimeError(
                        f"Relation {relation_id} "
                        "has inconsistent endpoints.\n"
                        f"First: {existing_signature}\n"
                        f"Later: {signature}"
                    )

                existing[
                    "appearances"
                ] += 1


# =========================================================
# Full pre-flight validation
# =========================================================

print("========================================")
print("PLANE RELATION IMPORT")
print("========================================")
print()

print(
    "Relation appearances:",
    appearance_count,
)

print(
    "Unique Linear relations:",
    len(unique_relations),
)


if appearance_count != 1730:
    raise RuntimeError(
        f"Expected 1730 relation appearances, "
        f"found {appearance_count}"
    )

if len(unique_relations) != 865:
    raise RuntimeError(
        f"Expected 865 unique relations, "
        f"found {len(unique_relations)}"
    )


# Every relation must appear exactly twice.

bad_appearance_counts = [
    relation
    for relation in unique_relations.values()
    if relation["appearances"] != 2
]

if bad_appearance_counts:
    raise RuntimeError(
        "Some relations do not appear exactly twice"
    )


# Validate endpoints exist in Plane mapping.

for relation in unique_relations.values():
    source = relation["source"]
    target = relation["target"]

    if source not in work_mapping:
        raise RuntimeError(
            f"{relation['id']}: source "
            f"{source} missing from work mapping"
        )

    if target not in work_mapping:
        raise RuntimeError(
            f"{relation['id']}: target "
            f"{target} missing from work mapping"
        )


# =========================================================
# Check logical duplicates
# =========================================================

logical_signatures = {}
logical_duplicates = []


for relation in unique_relations.values():
    source = relation["source"]
    target = relation["target"]

    if relation["type"] == "related":
        # Related is symmetric in Plane.
        left, right = sorted(
            [source, target],
            key=issue_number,
        )

        logical_signature = (
            "related",
            left,
            right,
        )

    else:
        # Blocks is directional.
        logical_signature = (
            "blocks",
            source,
            target,
        )

    if logical_signature in logical_signatures:
        logical_duplicates.append(
            {
                "signature": logical_signature,
                "first": logical_signatures[
                    logical_signature
                ],
                "second": relation["id"],
            }
        )
    else:
        logical_signatures[
            logical_signature
        ] = relation["id"]


if logical_duplicates:
    print()
    print("LOGICAL DUPLICATES FOUND")

    print(
        json.dumps(
            logical_duplicates,
            indent=2,
        )
    )

    raise RuntimeError(
        "Plane cannot safely represent "
        "duplicate logical relations. "
        "Import stopped before writing."
    )


# =========================================================
# Validate counts
# =========================================================

type_counts = Counter(
    relation["type"]
    for relation
    in unique_relations.values()
)

print()
print("Relation types:")

for relation_type, count in sorted(
    type_counts.items()
):
    print(
        f"  {relation_type}: {count}"
    )


if type_counts["blocks"] != 29:
    raise RuntimeError(
        f"Expected 29 blocks relations, "
        f"found {type_counts['blocks']}"
    )

if type_counts["related"] != 836:
    raise RuntimeError(
        f"Expected 836 related relations, "
        f"found {type_counts['related']}"
    )


print()
print("All relations appear exactly twice: YES")
print("All endpoints mapped to Plane: YES")
print("Logical duplicate relations: 0")
print("Pre-flight validation: PASSED")
print()


# =========================================================
# Sort migration deterministically
# =========================================================

relations = sorted(
    unique_relations.values(),
    key=lambda relation: (
        issue_number(
            relation["source"]
        ),
        relation["type"],
        issue_number(
            relation["target"]
        ),
        relation["id"],
    ),
)


# =========================================================
# Plane relation cache
# =========================================================

relation_cache = {}


def normalize_plane_relations(data):
    result = {
        "blocking": set(),
        "blocked_by": set(),
        "duplicate": set(),
        "relates_to": set(),
        "start_after": set(),
        "start_before": set(),
        "finish_after": set(),
        "finish_before": set(),
    }

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected Plane relation response"
        )

    for relation_type in result:
        for entry in (
            data.get(relation_type)
            or []
        ):
            issue_id = entry.get(
                "issue_id"
            )

            if issue_id:
                result[
                    relation_type
                ].add(issue_id)

    return result


def get_plane_relation_state(
    identifier,
):
    if identifier in relation_cache:
        return relation_cache[
            identifier
        ]

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    data = request(
        "GET",
        relations_path(
            plane_id
        ),
    )

    normalized = (
        normalize_plane_relations(
            data
        )
    )

    relation_cache[
        identifier
    ] = normalized

    return normalized


# =========================================================
# Import
# =========================================================

created_count = 0
recovered_count = 0
already_mapped_count = 0


for index, relation in enumerate(
    relations,
    start=1,
):
    relation_id = relation["id"]

    source_identifier = (
        relation["source"]
    )

    target_identifier = (
        relation["target"]
    )

    source_plane_id = (
        work_mapping[
            source_identifier
        ]["plane_id"]
    )

    target_plane_id = (
        work_mapping[
            target_identifier
        ]["plane_id"]
    )

    if relation["type"] == "blocks":
        plane_relation_type = "blocking"
    else:
        plane_relation_type = "relates_to"

    print(
        f"[{index:03}/865] "
        f"{source_identifier} "
        f"{relation['type']} "
        f"{target_identifier}",
        end="",
        flush=True,
    )

    # -----------------------------------------------------
    # Read source relation state
    # -----------------------------------------------------

    source_state = (
        get_plane_relation_state(
            source_identifier
        )
    )

    exists_in_plane = (
        target_plane_id
        in source_state[
            plane_relation_type
        ]
    )

    # -----------------------------------------------------
    # Existing local mapping
    # -----------------------------------------------------

    if relation_id in relation_mapping:
        if not exists_in_plane:
            raise RuntimeError(
                f"\n{relation_id}: local mapping "
                "says relation exists, but Plane "
                "does not contain it."
            )

        already_mapped_count += 1

        print(
            " -> already mapped ✓"
        )

        continue

    # -----------------------------------------------------
    # Recover relation from Plane
    #
    # Handles:
    # POST succeeded previously but script stopped before
    # writing mapping JSON.
    # -----------------------------------------------------

    if exists_in_plane:
        relation_mapping[
            relation_id
        ] = {
            "linear_relation_id": (
                relation_id
            ),
            "linear_type": (
                relation["type"]
            ),
            "source": (
                source_identifier
            ),
            "target": (
                target_identifier
            ),
            "plane_relation_type": (
                plane_relation_type
            ),
        }

        save_relation_mapping()

        recovered_count += 1

        print(
            " -> recovered existing ✓"
        )

        continue

    # -----------------------------------------------------
    # Create Plane relation
    # -----------------------------------------------------

    request(
        "POST",
        relations_path(
            source_plane_id
        ),
        json={
            "relation_type": (
                plane_relation_type
            ),
            "issues": [
                target_plane_id,
            ],
        },
    )

    # Update local cache immediately.

    source_state[
        plane_relation_type
    ].add(
        target_plane_id
    )

    # If target was already loaded into cache,
    # keep its inverse view synchronized too.

    if target_identifier in relation_cache:
        target_state = relation_cache[
            target_identifier
        ]

        if plane_relation_type == "blocking":
            target_state[
                "blocked_by"
            ].add(
                source_plane_id
            )

        elif plane_relation_type == "relates_to":
            target_state[
                "relates_to"
            ].add(
                source_plane_id
            )

    relation_mapping[
        relation_id
    ] = {
        "linear_relation_id": (
            relation_id
        ),
        "linear_type": (
            relation["type"]
        ),
        "source": (
            source_identifier
        ),
        "target": (
            target_identifier
        ),
        "plane_relation_type": (
            plane_relation_type
        ),
    }

    # Save after every successful relation.
    save_relation_mapping()

    created_count += 1

    print(" -> created ✓")


# =========================================================
# Mapping validation
# =========================================================

source_relation_ids = set(
    unique_relations.keys()
)

mapped_relation_ids = (
    set(relation_mapping.keys())
    & source_relation_ids
)

missing_relation_ids = (
    source_relation_ids
    - mapped_relation_ids
)


print()
print("========================================")
print("RELATION MAPPING VALIDATION")
print("========================================")

print(
    "Source relations:",
    len(source_relation_ids),
)

print(
    "Mapped relations:",
    len(mapped_relation_ids),
)

print(
    "Created this run:",
    created_count,
)

print(
    "Recovered existing:",
    recovered_count,
)

print(
    "Already mapped:",
    already_mapped_count,
)


if missing_relation_ids:
    print()
    print("VALIDATION FAILED")

    for relation_id in sorted(
        missing_relation_ids
    ):
        print(
            "Missing:",
            relation_id,
        )

    raise SystemExit(1)


# =========================================================
# Fresh final verification
# =========================================================

print()
print(
    "Performing fresh verification "
    "against Plane..."
)

fresh_states = {}

for index in range(1, 221):
    identifier = f"HOR-{index}"

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    data = request(
        "GET",
        relations_path(
            plane_id
        ),
    )

    fresh_states[
        identifier
    ] = normalize_plane_relations(
        data
    )


verified_relations = 0


for relation in relations:
    source_identifier = (
        relation["source"]
    )

    target_identifier = (
        relation["target"]
    )

    target_plane_id = (
        work_mapping[
            target_identifier
        ]["plane_id"]
    )

    if relation["type"] == "blocks":
        plane_relation_type = (
            "blocking"
        )
    else:
        plane_relation_type = (
            "relates_to"
        )

    if (
        target_plane_id
        not in fresh_states[
            source_identifier
        ][plane_relation_type]
    ):
        raise RuntimeError(
            f"Final verification failed: "
            f"{source_identifier} "
            f"{relation['type']} "
            f"{target_identifier}"
        )

    verified_relations += 1


# =========================================================
# Global Plane relation counts
# =========================================================

global_counts = Counter()

for state in fresh_states.values():
    for relation_type, targets in (
        state.items()
    ):
        global_counts[
            relation_type
        ] += len(targets)


print()
print("Plane relation appearances:")

for relation_type in (
    "blocking",
    "blocked_by",
    "relates_to",
    "duplicate",
    "start_after",
    "start_before",
    "finish_after",
    "finish_before",
):
    print(
        f"  {relation_type}: "
        f"{global_counts[relation_type]}"
    )


# Expected Plane representation:
#
# 29 blocks:
#   29 blocking
#   29 blocked_by
#
# 836 related:
#   visible on both ends
#   836 * 2 = 1672 relates_to

if global_counts["blocking"] != 29:
    raise RuntimeError(
        "Expected 29 Plane blocking appearances"
    )

if global_counts["blocked_by"] != 29:
    raise RuntimeError(
        "Expected 29 Plane blocked_by appearances"
    )

if global_counts["relates_to"] != 1672:
    raise RuntimeError(
        "Expected 1672 Plane relates_to appearances"
    )


unexpected_types = (
    global_counts["duplicate"]
    + global_counts["start_after"]
    + global_counts["start_before"]
    + global_counts["finish_after"]
    + global_counts["finish_before"]
)

if unexpected_types != 0:
    raise RuntimeError(
        "Unexpected additional Plane "
        "relation types found"
    )


if verified_relations != 865:
    raise RuntimeError(
        f"Expected 865 verified relations, "
        f"got {verified_relations}"
    )


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("RELATION IMPORT COMPLETE")
print("========================================")

print(
    "Linear unique relations:",
    len(unique_relations),
)

print(
    "Blocks migrated:",
    type_counts["blocks"],
)

print(
    "Related migrated:",
    type_counts["related"],
)

print(
    "Relations verified:",
    verified_relations,
)

print()

print(
    "All 865 Linear relations "
    "are represented in Plane: YES"
)

print()

print(
    "Mapping:",
    relation_mapping_path,
)