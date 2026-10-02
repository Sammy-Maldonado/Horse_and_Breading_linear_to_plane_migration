import json
import os
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
    "Content-Type": "application/json",
}

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
            if attempt >= MAX_RATE_LIMIT_RETRIES:
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

            print(
                f"Rate limit reached. "
                f"Waiting {wait_seconds:.0f}s..."
            )

            time.sleep(wait_seconds)
            continue

        if not response.ok:
            print()
            print("Plane API error")
            print(method, path)
            print("Status:", response.status_code)
            print(response.text)

            response.raise_for_status()

        if response.status_code == 204:
            return None

        return response.json()

    raise RuntimeError(
        "Unexpected retry failure"
    )


# =========================================================
# Load source backup
# =========================================================

backups = sorted(
    BACKUP_DIR.glob(
        "linear_backup_*.json"
    ),
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

with (
    BACKUP_DIR
    / "linear_to_plane_mapping.json"
).open(
    "r",
    encoding="utf-8",
) as file:
    work_mapping = json.load(file)


with (
    BACKUP_DIR
    / "linear_to_plane_comment_mapping.json"
).open(
    "r",
    encoding="utf-8",
) as file:
    comment_mapping = json.load(file)


# =========================================================
# Collection helper
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
# Plane paths
# =========================================================

def comments_path(plane_work_item_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_work_item_id}/comments/"
    )


def get_comments(plane_work_item_id):
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
            comments_path(
                plane_work_item_id
            ),
            params=params,
        )

        if isinstance(data, list):
            results.extend(data)
            break

        results.extend(
            data.get("results", [])
        )

        if not data.get(
            "next_page_results"
        ):
            break

        cursor = data.get(
            "next_cursor"
        )

        if not cursor:
            break

    return results


# =========================================================
# Find the 3 Linear replies
# =========================================================

replies = []


for issue in issues:
    identifier = issue["identifier"]

    for comment in extract_collection(
        issue.get("comments")
    ):
        parent = comment.get("parent")

        if not parent:
            continue

        replies.append({
            "issue": identifier,
            "linear_reply_id": comment["id"],
            "linear_parent_id": parent["id"],
        })


print("========================================")
print("COMMENT REPLY INSPECTION")
print("========================================")
print()

print("Linear replies found:", len(replies))

if len(replies) != 3:
    raise RuntimeError(
        f"Expected 3 replies, found "
        f"{len(replies)}"
    )


# =========================================================
# Inspect each reply in Plane
# =========================================================

for index, reply in enumerate(
    replies,
    start=1,
):
    identifier = reply["issue"]

    linear_reply_id = (
        reply["linear_reply_id"]
    )

    linear_parent_id = (
        reply["linear_parent_id"]
    )

    plane_work_item_id = (
        work_mapping[
            identifier
        ]["plane_id"]
    )

    expected_reply_plane_id = (
        comment_mapping[
            linear_reply_id
        ]["plane_id"]
    )

    expected_parent_plane_id = (
        comment_mapping[
            linear_parent_id
        ]["plane_id"]
    )

    comments = get_comments(
        plane_work_item_id
    )

    comments_by_id = {
        comment["id"]: comment
        for comment in comments
    }

    plane_reply = comments_by_id.get(
        expected_reply_plane_id
    )

    plane_parent = comments_by_id.get(
        expected_parent_plane_id
    )

    print()
    print("========================================")
    print(
        f"REPLY {index}/3 — {identifier}"
    )
    print("========================================")

    print()
    print(
        "Linear reply ID:",
        linear_reply_id,
    )

    print(
        "Linear parent ID:",
        linear_parent_id,
    )

    print()
    print(
        "Expected Plane reply ID:",
        expected_reply_plane_id,
    )

    print(
        "Expected Plane parent ID:",
        expected_parent_plane_id,
    )

    print()

    if plane_reply is None:
        print(
            "ERROR: mapped Plane reply "
            "not found."
        )
    else:
        print("PLANE REPLY RAW:")
        print(
            json.dumps(
                plane_reply,
                ensure_ascii=False,
                indent=2,
            )
        )

    print()

    if plane_parent is None:
        print(
            "ERROR: mapped Plane parent "
            "comment not found."
        )
    else:
        print("EXPECTED PARENT RAW:")
        print(
            json.dumps(
                plane_parent,
                ensure_ascii=False,
                indent=2,
            )
        )


print()
print("========================================")
print("INSPECTION COMPLETE")
print("========================================")
print()

print(
    "No data was modified in Plane."
)