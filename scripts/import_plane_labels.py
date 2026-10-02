import json
import os
import time
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

            retry_after = response.headers.get("Retry-After")

            try:
                wait_seconds = float(retry_after)
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

with backup_path.open("r", encoding="utf-8") as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Load work-item mapping
# =========================================================

mapping_path = (
    backup_dir
    / "linear_to_plane_mapping.json"
)

if not mapping_path.exists():
    raise RuntimeError(
        "linear_to_plane_mapping.json not found"
    )

with mapping_path.open("r", encoding="utf-8") as file:
    work_item_mapping = json.load(file)

if len(work_item_mapping) != 220:
    raise RuntimeError(
        f"Expected 220 work-item mappings, "
        f"found {len(work_item_mapping)}"
    )


# =========================================================
# Helpers
# =========================================================

def extract_labels(issue):
    labels = issue.get("labels") or {}

    if isinstance(labels, list):
        return labels

    if isinstance(labels, dict):
        if isinstance(labels.get("nodes"), list):
            return labels["nodes"]

        if isinstance(labels.get("results"), list):
            return labels["results"]

    return []


def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


issues.sort(key=issue_number)


# =========================================================
# Build source label inventory
# =========================================================

source_labels = {}
issue_labels = {}


for issue in issues:
    identifier = issue["identifier"]

    labels = extract_labels(issue)

    issue_label_ids = []

    for label in labels:
        linear_label_id = label.get("id")
        name = label.get("name")

        if not linear_label_id:
            raise RuntimeError(
                f"{identifier}: label without ID"
            )

        if not name:
            raise RuntimeError(
                f"{identifier}: label without name"
            )

        if linear_label_id not in source_labels:
            source_labels[linear_label_id] = {
                "id": linear_label_id,
                "name": name,
                "color": label.get("color"),
                "description": (
                    label.get("description")
                    or ""
                ),
            }
        else:
            existing = source_labels[
                linear_label_id
            ]

            if existing["name"] != name:
                raise RuntimeError(
                    f"Linear label {linear_label_id} "
                    f"has inconsistent names"
                )

        issue_label_ids.append(
            linear_label_id
        )

    issue_labels[identifier] = (
        issue_label_ids
    )


print("========================================")
print("PLANE LABEL IMPORT")
print("========================================")
print()

print(
    "Distinct Linear labels:",
    len(source_labels),
)

print(
    "Work items with labels:",
    sum(
        1
        for labels in issue_labels.values()
        if labels
    ),
)

print()


if len(source_labels) != 1:
    raise RuntimeError(
        f"Expected exactly 1 Linear label, "
        f"found {len(source_labels)}"
    )


for label in source_labels.values():
    print(
        "Linear label:",
        label["name"],
        "| id=",
        label["id"],
        "| color=",
        label["color"],
    )


# =========================================================
# Plane label endpoints
# =========================================================

labels_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
    f"{PLANE_PROJECT_ID}/labels/"
)


def work_item_path(plane_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_id}/"
    )


# =========================================================
# Read all existing Plane labels
# =========================================================

def get_plane_labels():
    results = []
    cursor = None

    while True:
        params = {
            "per_page": 100,
        }

        if cursor:
            params["cursor"] = cursor

        data = request(
            "GET",
            labels_path,
            params=params,
        )

        if isinstance(data, list):
            results.extend(data)
            break

        results.extend(
            data.get("results", [])
        )

        if not data.get("next_page_results"):
            break

        cursor = data.get("next_cursor")

        if not cursor:
            break

    return results


plane_labels = get_plane_labels()


# =========================================================
# Create/recover Linear labels
# =========================================================

label_mapping = {}

created_labels = 0
existing_labels = 0


for linear_id, source_label in (
    source_labels.items()
):
    match = None

    # Preferred: migration metadata
    for plane_label in plane_labels:
        if (
            plane_label.get("external_source")
            == "linear"
            and plane_label.get("external_id")
            == linear_id
        ):
            match = plane_label
            break

    # Fallback: exact name
    if match is None:
        for plane_label in plane_labels:
            if (
                plane_label.get("name")
                == source_label["name"]
            ):
                external_source = (
                    plane_label.get(
                        "external_source"
                    )
                )

                external_id = (
                    plane_label.get(
                        "external_id"
                    )
                )

                if (
                    external_id
                    and external_id != linear_id
                ):
                    raise RuntimeError(
                        f"Plane label "
                        f"{source_label['name']!r} "
                        "already exists with a "
                        "different external_id"
                    )

                match = plane_label
                break

    # -----------------------------------------------------
    # Create missing label
    # -----------------------------------------------------

    if match is None:
        payload = {
            "name": source_label["name"],
            "external_source": "linear",
            "external_id": linear_id,
        }

        if source_label["color"]:
            payload["color"] = (
                source_label["color"]
            )

        if source_label["description"]:
            payload["description"] = (
                source_label["description"]
            )

        match = request(
            "POST",
            labels_path,
            json=payload,
        )

        created_labels += 1

        print(
            f"Created Plane label: "
            f"{source_label['name']} ✓"
        )

    else:
        existing_labels += 1

        print(
            f"Plane label already exists: "
            f"{source_label['name']} ✓"
        )

    label_mapping[linear_id] = (
        match["id"]
    )


# =========================================================
# Save label mapping
# =========================================================

label_mapping_path = (
    backup_dir
    / "linear_to_plane_label_mapping.json"
)

with label_mapping_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        label_mapping,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Apply labels to work items
# =========================================================

print()
print("Applying labels to work items...")
print()

updated_items = 0


for issue in issues:
    identifier = issue["identifier"]

    linear_label_ids = (
        issue_labels[identifier]
    )

    if not linear_label_ids:
        continue

    plane_label_ids = [
        label_mapping[label_id]
        for label_id in linear_label_ids
    ]

    plane_work_item_id = (
        work_item_mapping[
            identifier
        ]["plane_id"]
    )

    updated = request(
        "PATCH",
        work_item_path(
            plane_work_item_id
        ),
        json={
            "labels": plane_label_ids,
        },
    )

    returned_labels = (
        updated.get("labels") or []
    )

    if set(returned_labels) != set(
        plane_label_ids
    ):
        raise RuntimeError(
            f"{identifier}: label verification "
            f"failed immediately after PATCH.\n"
            f"Expected: {plane_label_ids}\n"
            f"Returned: {returned_labels}"
        )

    updated_items += 1

    print(
        f"{identifier} -> label assigned ✓"
    )


# =========================================================
# Final verification
# =========================================================

print()
print("Verifying labels...")

verified_items = 0


for issue in issues:
    identifier = issue["identifier"]

    linear_label_ids = (
        issue_labels[identifier]
    )

    if not linear_label_ids:
        continue

    expected_plane_labels = {
        label_mapping[label_id]
        for label_id in linear_label_ids
    }

    plane_work_item_id = (
        work_item_mapping[
            identifier
        ]["plane_id"]
    )

    item = request(
        "GET",
        work_item_path(
            plane_work_item_id
        ),
    )

    actual_labels = set(
        item.get("labels") or []
    )

    if actual_labels != expected_plane_labels:
        raise RuntimeError(
            f"{identifier}: final label "
            f"verification failed.\n"
            f"Expected: "
            f"{sorted(expected_plane_labels)}\n"
            f"Actual: "
            f"{sorted(actual_labels)}"
        )

    verified_items += 1


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("LABEL IMPORT COMPLETE")
print("========================================")

print(
    "Source labels:",
    len(source_labels),
)

print(
    "Plane labels created:",
    created_labels,
)

print(
    "Plane labels already existing:",
    existing_labels,
)

print(
    "Work items updated:",
    updated_items,
)

print(
    "Work items verified:",
    verified_items,
)

print()

print(
    "Label mapping:",
    label_mapping_path,
)

print()

print(
    "GitHub links and issue relations "
    "have NOT been migrated yet."
)