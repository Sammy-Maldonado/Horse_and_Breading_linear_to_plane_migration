import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================================================
# Configuration
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

load_dotenv(ROOT_DIR / ".env")

PLANE_BASE_URL = os.getenv("PLANE_BASE_URL")
PLANE_WORKSPACE_SLUG = os.getenv("PLANE_WORKSPACE_SLUG")
PLANE_API_KEY = os.getenv("PLANE_API_KEY")

if not all([
    PLANE_BASE_URL,
    PLANE_WORKSPACE_SLUG,
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
                wait_seconds = float(retry_after)
            except (TypeError, ValueError):
                wait_seconds = 65

            print(
                f"Rate limit reached. "
                f"Waiting {wait_seconds:.0f}s..."
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
# Paths
# =========================================================

projects_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
)


def items_path(project_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{project_id}/work-items/"
    )


def relations_path(
    project_id,
    work_item_id,
):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{project_id}/work-items/"
        f"{work_item_id}/relations/"
    )


# =========================================================
# Temporary project
# =========================================================

timestamp = datetime.now().strftime(
    "%H%M%S"
)

identifier = f"REL{timestamp}"

project_id = None


try:
    print("Creating temporary project...")

    project = request(
        "POST",
        projects_path,
        json={
            "name": "Migration Relation Test",
            "identifier": identifier,
            "description": (
                "Temporary project for "
                "relation migration test."
            ),
            "cycle_view": False,
            "module_view": False,
            "issue_views_view": False,
            "page_view": False,
            "intake_view": False,
        },
    )

    project_id = project["id"]

    print(
        "Temporary project:",
        identifier,
    )

    print(
        "Project ID:",
        project_id,
    )

    print()

    # =====================================================
    # Create three temporary work items
    # =====================================================

    item_a = request(
        "POST",
        items_path(project_id),
        json={
            "name": "Relation test A",
        },
    )

    item_b = request(
        "POST",
        items_path(project_id),
        json={
            "name": "Relation test B",
        },
    )

    item_c = request(
        "POST",
        items_path(project_id),
        json={
            "name": "Relation test C",
        },
    )

    print(
        "A:",
        f"{identifier}-{item_a['sequence_id']}",
        item_a["id"],
    )

    print(
        "B:",
        f"{identifier}-{item_b['sequence_id']}",
        item_b["id"],
    )

    print(
        "C:",
        f"{identifier}-{item_c['sequence_id']}",
        item_c["id"],
    )

    print()

    # =====================================================
    # Test BLOCKING
    #
    # A blocks B
    # =====================================================

    print("Creating: A BLOCKS B")

    blocking_response = request(
        "POST",
        relations_path(
            project_id,
            item_a["id"],
        ),
        json={
            "relation_type": "blocking",
            "issues": [
                item_b["id"],
            ],
        },
    )

    print(
        json.dumps(
            blocking_response,
            indent=2,
        )
    )

    print()

    # =====================================================
    # Test RELATED
    #
    # A relates to C
    # =====================================================

    print("Creating: A RELATES_TO C")

    related_response = request(
        "POST",
        relations_path(
            project_id,
            item_a["id"],
        ),
        json={
            "relation_type": "relates_to",
            "issues": [
                item_c["id"],
            ],
        },
    )

    print(
        json.dumps(
            related_response,
            indent=2,
        )
    )

    print()

    # =====================================================
    # Read relations from all sides
    # =====================================================

    print("========================================")
    print("RELATIONS FROM A")
    print("========================================")

    relations_a = request(
        "GET",
        relations_path(
            project_id,
            item_a["id"],
        ),
    )

    print(
        json.dumps(
            relations_a,
            indent=2,
        )
    )

    print()

    print("========================================")
    print("RELATIONS FROM B")
    print("========================================")

    relations_b = request(
        "GET",
        relations_path(
            project_id,
            item_b["id"],
        ),
    )

    print(
        json.dumps(
            relations_b,
            indent=2,
        )
    )

    print()

    print("========================================")
    print("RELATIONS FROM C")
    print("========================================")

    relations_c = request(
        "GET",
        relations_path(
            project_id,
            item_c["id"],
        ),
    )

    print(
        json.dumps(
            relations_c,
            indent=2,
        )
    )

    print()

    print("========================================")
    print("RELATION TEST COMPLETE")
    print("========================================")

    print()
    print(
        "Expected:"
    )

    print(
        "A should show B under blocking."
    )

    print(
        "B should show A under blocked_by."
    )

    print(
        "A and C should show each other "
        "under relates_to."
    )


finally:
    # =====================================================
    # Delete temporary project
    # =====================================================

    if project_id:
        print()
        print(
            "Deleting temporary project..."
        )

        try:
            request(
                "DELETE",
                (
                    f"/api/v1/workspaces/"
                    f"{PLANE_WORKSPACE_SLUG}/"
                    f"projects/{project_id}/"
                ),
            )

            print(
                "Temporary project "
                "deleted successfully."
            )

        except Exception as exc:
            print()
            print(
                "WARNING: temporary project "
                "could not be deleted."
            )

            print(exc)

            print()
            print(
                "Delete 'Migration Relation Test' "
                "manually in Plane."
            )


print()
print(
    "HOR project was never touched."
)