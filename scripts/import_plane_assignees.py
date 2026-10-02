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
LINEAR_EMAIL = (
    os.getenv("LINEAR_EMAIL")
    or ""
).strip().lower()

if not all([
    PLANE_BASE_URL,
    PLANE_WORKSPACE_SLUG,
    PLANE_PROJECT_ID,
    PLANE_API_KEY,
    LINEAR_EMAIL,
]):
    raise RuntimeError(
        "Missing required environment variables"
    )


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

    for attempt in range(
        MAX_RATE_LIMIT_RETRIES + 1
    ):
        response = requests.request(
            method,
            url,
            headers=HEADERS,
            timeout=60,
            **kwargs,
        )

        if response.status_code == 429:
            if (
                attempt
                >= MAX_RATE_LIMIT_RETRIES
            ):
                print(
                    "Rate limit retry limit reached."
                )
                print(response.text)

                response.raise_for_status()

            retry_after = (
                response.headers.get(
                    "Retry-After"
                )
            )

            try:
                wait_seconds = float(
                    retry_after
                )
            except (
                TypeError,
                ValueError,
            ):
                wait_seconds = 65

            print()
            print(
                f"Plane rate limit reached. "
                f"Waiting "
                f"{wait_seconds:.0f} seconds..."
            )

            time.sleep(wait_seconds)
            continue

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

        if not response.ok:
            print()
            print("Plane API error")
            print(method, path)
            print(
                "Status:",
                response.status_code,
            )
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
# Load backup
# =========================================================

backup_dir = BACKUP_DIR

backups = sorted(
    backup_dir.glob(
        "linear_backup_*.json"
    ),
    key=lambda path: (
        path.stat().st_mtime
    ),
)

if not backups:
    raise RuntimeError(
        "No Linear backup found"
    )

backup_path = backups[-1]

with backup_path.open(
    "r",
    encoding="utf-8",
) as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Work-item mapping
# =========================================================

mapping_path = (
    backup_dir
    / "linear_to_plane_mapping.json"
)

with mapping_path.open(
    "r",
    encoding="utf-8",
) as file:
    mapping = json.load(file)

if len(mapping) != 220:
    raise RuntimeError(
        f"Expected 220 mappings, "
        f"found {len(mapping)}"
    )


# =========================================================
# Identify current Plane user
# =========================================================

me = request(
    "GET",
    "/api/v1/users/me/",
)

plane_user_id = me.get("id")
plane_email = (
    me.get("email")
    or ""
).lower()

if not plane_user_id:
    raise RuntimeError(
        "Plane current user has no ID"
    )


# =========================================================
# Validate Linear users
# =========================================================

creator_ids = set()
creator_emails = set()

assignee_ids = set()
assignee_emails = set()


for issue in issues:
    creator = issue.get(
        "creator"
    )

    if creator:
        creator_ids.add(
            creator.get("id")
        )

        creator_emails.add(
            (
                creator.get("email")
                or ""
            ).lower()
        )

    assignee = issue.get(
        "assignee"
    )

    if assignee:
        assignee_ids.add(
            assignee.get("id")
        )

        assignee_emails.add(
            (
                assignee.get("email")
                or ""
            ).lower()
        )


if creator_emails != {
    LINEAR_EMAIL
}:
    raise RuntimeError(
        f"Unexpected Linear creators: "
        f"{creator_emails}"
    )


if assignee_emails != {
    LINEAR_EMAIL
}:
    raise RuntimeError(
        f"Unexpected Linear assignees: "
        f"{assignee_emails}"
    )


if plane_email != LINEAR_EMAIL:
    raise RuntimeError(
        "Plane current user email "
        "does not match Linear user.\n"
        f"Plane:  {plane_email}\n"
        f"Linear: {LINEAR_EMAIL}"
    )


print("========================================")
print("PLANE ASSIGNEE MIGRATION")
print("========================================")
print()

print(
    "Plane user:",
    plane_email,
)

print(
    "Plane user ID:",
    plane_user_id,
)

print()

print(
    "Linear assigned issues:",
    sum(
        1
        for issue in issues
        if issue.get("assignee")
    ),
)

print(
    "Linear unassigned issues:",
    sum(
        1
        for issue in issues
        if not issue.get("assignee")
    ),
)

print()


# =========================================================
# Helpers
# =========================================================

def issue_number(issue):
    return int(
        issue["identifier"]
        .split("-")[1]
    )


def work_item_path(plane_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/"
        f"projects/"
        f"{PLANE_PROJECT_ID}/"
        f"work-items/"
        f"{plane_id}/"
    )


def normalize_assignees(value):
    if not value:
        return set()

    result = set()

    for entry in value:
        if isinstance(
            entry,
            str,
        ):
            result.add(entry)

        elif isinstance(
            entry,
            dict,
        ):
            user_id = (
                entry.get("id")
                or entry.get(
                    "member_id"
                )
            )

            if user_id:
                result.add(
                    user_id
                )

    return result


issues.sort(
    key=issue_number
)


# =========================================================
# Apply exact assignment state
# =========================================================

assigned_updates = 0
unassigned_updates = 0


for index, issue in enumerate(
    issues,
    start=1,
):
    identifier = (
        issue["identifier"]
    )

    plane_id = (
        mapping[
            identifier
        ]["plane_id"]
    )

    if issue.get("assignee"):
        wanted = [
            plane_user_id
        ]
    else:
        wanted = []

    updated = request(
        "PATCH",
        work_item_path(
            plane_id
        ),
        json={
            "assignees": wanted,
        },
    )

    returned = normalize_assignees(
        updated.get(
            "assignees"
        )
    )

    # Some Plane responses may not return
    # assignees. Final GET verification below
    # remains authoritative.
    if returned:
        if returned != set(wanted):
            raise RuntimeError(
                f"{identifier}: "
                "unexpected assignee "
                "response.\n"
                f"Expected: {wanted}\n"
                f"Returned: {returned}"
            )

    if wanted:
        assigned_updates += 1
        status = "assigned"
    else:
        unassigned_updates += 1
        status = "unassigned"

    print(
        f"[{index:03}/220] "
        f"{identifier} "
        f"-> {status} ✓"
    )


# =========================================================
# Final verification
# =========================================================

print()
print(
    "Verifying assignees..."
)

verified_assigned = 0
verified_unassigned = 0


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    plane_id = (
        mapping[
            identifier
        ]["plane_id"]
    )

    item = request(
        "GET",
        work_item_path(
            plane_id
        ),
    )

    actual = normalize_assignees(
        item.get(
            "assignees"
        )
    )

    if issue.get("assignee"):
        expected = {
            plane_user_id
        }

        if actual != expected:
            raise RuntimeError(
                f"{identifier}: "
                "assignee verification "
                "failed.\n"
                f"Expected: {expected}\n"
                f"Actual: {actual}"
            )

        verified_assigned += 1

    else:
        if actual:
            raise RuntimeError(
                f"{identifier}: "
                "should be unassigned, "
                f"but has {actual}"
            )

        verified_unassigned += 1


# =========================================================
# Preserve non-native Linear metadata
# =========================================================

metadata = {
    "source_backup": str(
        backup_path
    ),
    "purpose": (
        "Historical Linear metadata "
        "not represented natively in Plane"
    ),
    "issues": {},
    "comments": {},
}


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    project = (
        issue.get("project")
    )

    metadata["issues"][
        identifier
    ] = {
        "linear_id": (
            issue.get("id")
        ),
        "linear_number": (
            issue.get("number")
        ),
        "linear_url": (
            issue.get("url")
        ),
        "branch_name": (
            issue.get(
                "branchName"
            )
        ),
        "created_at": (
            issue.get(
                "createdAt"
            )
        ),
        "updated_at": (
            issue.get(
                "updatedAt"
            )
        ),
        "started_at": (
            issue.get(
                "startedAt"
            )
        ),
        "completed_at": (
            issue.get(
                "completedAt"
            )
        ),
        "canceled_at": (
            issue.get(
                "canceledAt"
            )
        ),
        "creator": (
            issue.get("creator")
        ),
        "assignee": (
            issue.get(
                "assignee"
            )
        ),
        "linear_project": (
            project
        ),
        "was_projectless": (
            project is None
        ),
        "linear_team": (
            issue.get("team")
        ),
    }

    comments = (
        issue.get("comments")
        or []
    )

    for comment in comments:
        comment_id = (
            comment.get("id")
        )

        if (
            comment_id
            and comment.get("url")
        ):
            metadata[
                "comments"
            ][comment_id] = {
                "issue": (
                    identifier
                ),
                "linear_url": (
                    comment.get(
                        "url"
                    )
                ),
            }


metadata_path = (
    backup_dir
    / "linear_historical_metadata.json"
)

with metadata_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        metadata,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Metadata validation
# =========================================================

if (
    len(
        metadata["issues"]
    )
    != 220
):
    raise RuntimeError(
        "Historical metadata "
        "issue count mismatch"
    )


if (
    len(
        metadata["comments"]
    )
    != 475
):
    raise RuntimeError(
        "Historical metadata "
        "comment URL count mismatch"
    )


projectless_count = sum(
    1
    for value
    in metadata[
        "issues"
    ].values()
    if value[
        "was_projectless"
    ]
)

if projectless_count != 31:
    raise RuntimeError(
        f"Expected 31 projectless "
        f"issues, found "
        f"{projectless_count}"
    )


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("ASSIGNEE MIGRATION COMPLETE")
print("========================================")

print(
    "Assigned issues verified:",
    verified_assigned,
)

print(
    "Unassigned issues verified:",
    verified_unassigned,
)

print()

print(
    "Historical issue metadata:",
    len(
        metadata["issues"]
    ),
)

print(
    "Historical comment URLs:",
    len(
        metadata["comments"]
    ),
)

print(
    "Source projectless issues:",
    projectless_count,
)

print()

print(
    "Metadata archive:",
    metadata_path,
)

print()

print(
    "No source metadata was silently discarded."
)