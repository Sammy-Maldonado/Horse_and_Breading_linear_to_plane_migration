import json
import os
import subprocess
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================================================
# Project paths
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BACKUP_DIR = ROOT_DIR / "backups"

load_dotenv(ROOT_DIR / ".env")


# =========================================================
# Configuration
# =========================================================

PLANE_BASE_URL = os.getenv("PLANE_BASE_URL")
PLANE_WORKSPACE_SLUG = os.getenv("PLANE_WORKSPACE_SLUG")
PLANE_PROJECT_ID = os.getenv("PLANE_PROJECT_ID")
PLANE_API_KEY = os.getenv("PLANE_API_KEY")

PLANE_API_CONTAINER = os.getenv(
    "PLANE_API_CONTAINER",
    "plane-app-api-1",
)

if not all([
    PLANE_BASE_URL,
    PLANE_WORKSPACE_SLUG,
    PLANE_PROJECT_ID,
    PLANE_API_KEY,
]):
    raise RuntimeError(
        "Missing Plane environment variables"
    )


HEADERS = {
    "X-API-Key": PLANE_API_KEY,
}


# =========================================================
# Load source backup
# =========================================================

backups = sorted(
    BACKUP_DIR.glob("linear_backup_*.json"),
    key=lambda path: path.stat().st_mtime,
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
# Load mappings
# =========================================================

def load_json(name):
    path = BACKUP_DIR / name

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


work_mapping = load_json(
    "linear_to_plane_mapping.json"
)

comment_mapping = load_json(
    "linear_to_plane_comment_mapping.json"
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


# =========================================================
# Find the 3 Linear reply relationships
# =========================================================

repairs = []


for issue in issues:
    identifier = issue["identifier"]

    for comment in extract_collection(
        issue.get("comments")
    ):
        parent = comment.get("parent")

        if not parent:
            continue

        linear_reply_id = comment["id"]
        linear_parent_id = parent["id"]

        repairs.append({
            "identifier": identifier,
            "linear_reply_id": linear_reply_id,
            "linear_parent_id": linear_parent_id,
            "plane_reply_id": (
                comment_mapping[
                    linear_reply_id
                ]["plane_id"]
            ),
            "plane_parent_id": (
                comment_mapping[
                    linear_parent_id
                ]["plane_id"]
            ),
            "plane_issue_id": (
                work_mapping[
                    identifier
                ]["plane_id"]
            ),
        })


if len(repairs) != 3:
    raise RuntimeError(
        f"Expected exactly 3 reply repairs, "
        f"found {len(repairs)}"
    )


print("========================================")
print("PLANE COMMENT PARENT REPAIR")
print("========================================")
print()

for repair in repairs:
    print(
        f"{repair['identifier']}: "
        f"{repair['linear_reply_id'][:8]} "
        "-> "
        f"{repair['linear_parent_id'][:8]}"
    )


# =========================================================
# Build Django repair program
# =========================================================

repairs_json = json.dumps(
    repairs
)

django_code = f"""
import json

from django.db import transaction
from plane.db.models import IssueComment


repairs = json.loads({repairs_json!r})
expected_project_id = {PLANE_PROJECT_ID!r}


with transaction.atomic():

    for repair in repairs:

        reply = (
            IssueComment.objects
            .select_for_update()
            .get(pk=repair["plane_reply_id"])
        )

        parent = (
            IssueComment.objects
            .select_for_update()
            .get(pk=repair["plane_parent_id"])
        )

        # -----------------------------------------
        # Strict provenance validation
        # -----------------------------------------

        if reply.external_source != "linear":
            raise RuntimeError(
                f"Reply {{reply.id}} "
                "is not a Linear comment"
            )

        if (
            reply.external_id
            != repair["linear_reply_id"]
        ):
            raise RuntimeError(
                f"Reply {{reply.id}} "
                "external_id mismatch"
            )

        if parent.external_source != "linear":
            raise RuntimeError(
                f"Parent {{parent.id}} "
                "is not a Linear comment"
            )

        if (
            parent.external_id
            != repair["linear_parent_id"]
        ):
            raise RuntimeError(
                f"Parent {{parent.id}} "
                "external_id mismatch"
            )

        # -----------------------------------------
        # Same Plane work item
        # -----------------------------------------

        if reply.issue_id != parent.issue_id:
            raise RuntimeError(
                "Reply and parent belong "
                "to different work items"
            )

        if (
            str(reply.issue_id)
            != repair["plane_issue_id"]
        ):
            raise RuntimeError(
                "Plane work-item mapping mismatch"
            )

        # -----------------------------------------
        # Same project/workspace
        # -----------------------------------------

        if reply.project_id != parent.project_id:
            raise RuntimeError(
                "Reply and parent belong "
                "to different projects"
            )

        if (
            str(reply.project_id)
            != expected_project_id
        ):
            raise RuntimeError(
                "Unexpected Plane project"
            )

        if (
            reply.workspace_id
            != parent.workspace_id
        ):
            raise RuntimeError(
                "Reply and parent belong "
                "to different workspaces"
            )

        # -----------------------------------------
        # Do not overwrite unexpected data
        # -----------------------------------------

        if (
            reply.parent_id is not None
            and reply.parent_id != parent.id
        ):
            raise RuntimeError(
                f"Reply {{reply.id}} already has "
                f"unexpected parent "
                f"{{reply.parent_id}}"
            )

        # -----------------------------------------
        # Repair
        # -----------------------------------------

        if reply.parent_id == parent.id:
            print(
                "ALREADY_CORRECT",
                reply.id,
                parent.id,
            )

            continue

        updated = (
            IssueComment.objects
            .filter(
                pk=reply.id,
                parent__isnull=True,
            )
            .update(
                parent_id=parent.id
            )
        )

        if updated != 1:
            raise RuntimeError(
                f"Failed to update reply "
                f"{{reply.id}}"
            )

        print(
            "UPDATED",
            reply.id,
            parent.id,
        )
"""


# =========================================================
# Execute inside Plane's Django container
# =========================================================

shell_command = (
    'MANAGE=$(find /app /code '
    '-maxdepth 4 -name manage.py '
    '-print -quit 2>/dev/null); '
    'if [ -z "$MANAGE" ]; then '
    'echo "manage.py not found" >&2; '
    'exit 2; '
    'fi; '
    'cd "$(dirname "$MANAGE")"; '
    'python manage.py shell'
)


print()
print(
    "Applying controlled ORM repair..."
)
print()


result = subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        PLANE_API_CONTAINER,
        "sh",
        "-lc",
        shell_command,
    ],
    input=django_code,
    text=True,
    capture_output=True,
)


if result.stdout:
    print(result.stdout)

if result.stderr:
    print(result.stderr)


if result.returncode != 0:
    raise RuntimeError(
        "Django repair failed. "
        "Transaction was not completed."
    )


# =========================================================
# Plane API verification
# =========================================================

def get_comments(plane_issue_id):
    path = (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_issue_id}/comments/"
    )

    response = requests.get(
        f"{PLANE_BASE_URL}{path}",
        headers=HEADERS,
        params={
            "per_page": 100,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return data

    return data.get(
        "results",
        []
    )


def normalize_parent(value):
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return value.get("id")

    return None


verified = 0


print()
print(
    "Verifying repaired relationships "
    "through Plane API..."
)


for repair in repairs:
    comments = get_comments(
        repair["plane_issue_id"]
    )

    plane_reply = next(
        (
            comment
            for comment in comments
            if (
                comment.get("id")
                == repair["plane_reply_id"]
            )
        ),
        None,
    )

    if plane_reply is None:
        raise RuntimeError(
            f"{repair['identifier']}: "
            "repaired reply not found"
        )

    actual_parent = normalize_parent(
        plane_reply.get("parent")
    )

    expected_parent = (
        repair["plane_parent_id"]
    )

    if actual_parent != expected_parent:
        raise RuntimeError(
            f"{repair['identifier']}: "
            "parent verification failed.\n"
            f"Expected: {expected_parent}\n"
            f"Actual:   {actual_parent}"
        )

    verified += 1

    print(
        f"{repair['identifier']} "
        "-> parent verified ✓"
    )


if verified != 3:
    raise RuntimeError(
        f"Expected 3 verified replies, "
        f"got {verified}"
    )


print()
print("========================================")
print("COMMENT PARENT REPAIR COMPLETE")
print("========================================")
print()

print(
    "Native Plane reply relationships "
    "verified: 3 / 3"
)