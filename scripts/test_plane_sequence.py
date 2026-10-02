import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


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


def request(method, path, **kwargs):
    url = f"{PLANE_BASE_URL}{path}"

    response = requests.request(
        method,
        url,
        headers=HEADERS,
        timeout=30,
        **kwargs,
    )

    if not response.ok:
        print()
        print(method, path)
        print("Status:", response.status_code)
        print(response.text)

    response.raise_for_status()

    if response.status_code == 204:
        return None

    return response.json()


# =========================================================
# Temporary project
# =========================================================

timestamp = datetime.now().strftime("%H%M%S")

identifier = f"MIG{timestamp}"
project_id = None

try:
    print("Creating temporary project...")

    project = request(
        "POST",
        (
            f"/api/v1/workspaces/"
            f"{PLANE_WORKSPACE_SLUG}/projects/"
        ),
        json={
            "name": "Migration Sequence Test",
            "identifier": identifier,
            "description": (
                "Temporary project for Linear migration testing. "
                "Safe to delete."
            ),
            "cycle_view": False,
            "module_view": False,
            "issue_views_view": False,
            "page_view": False,
            "intake_view": False,
        },
    )

    project_id = project["id"]

    print("Temporary project:", identifier)
    print("Project ID:", project_id)
    print()

    # =====================================================
    # Test explicit sequence 37
    # =====================================================

    print("Creating explicit sequence_id=37...")

    item_37 = request(
        "POST",
        (
            f"/api/v1/workspaces/"
            f"{PLANE_WORKSPACE_SLUG}/projects/"
            f"{project_id}/work-items/"
        ),
        json={
            "name": "Sequence test 37",
            "priority": "medium",
            "sequence_id": 37,
            "external_source": "linear-migration-test",
            "external_id": "test-37",
        },
    )

    returned_37 = item_37.get("sequence_id")

    print(
        "Requested: 37 | Returned:",
        returned_37,
    )

    # =====================================================
    # Test explicit sequence 5
    # =====================================================

    print("Creating explicit sequence_id=5...")

    item_5 = request(
        "POST",
        (
            f"/api/v1/workspaces/"
            f"{PLANE_WORKSPACE_SLUG}/projects/"
            f"{project_id}/work-items/"
        ),
        json={
            "name": "Sequence test 5",
            "priority": "low",
            "sequence_id": 5,
            "external_source": "linear-migration-test",
            "external_id": "test-5",
        },
    )

    returned_5 = item_5.get("sequence_id")

    print(
        "Requested: 5 | Returned:",
        returned_5,
    )

    # =====================================================
    # Verify using identifier endpoint
    # =====================================================

    print()
    print("Verifying identifiers...")

    retrieved_37 = request(
        "GET",
        (
            f"/api/v1/workspaces/"
            f"{PLANE_WORKSPACE_SLUG}/work-items/"
            f"{identifier}-37/"
        ),
    )

    retrieved_5 = request(
        "GET",
        (
            f"/api/v1/workspaces/"
            f"{PLANE_WORKSPACE_SLUG}/work-items/"
            f"{identifier}-5/"
        ),
    )

    print(
        f"{identifier}-37:",
        retrieved_37.get("name"),
    )

    print(
        f"{identifier}-5:",
        retrieved_5.get("name"),
    )

    print()
    print("========================================")

    if (
        returned_37 == 37
        and returned_5 == 5
    ):
        print("EXPLICIT SEQUENCE IDs SUPPORTED")
        print()
        print(
            "We can preserve HOR-1 -> HOR-220 exactly."
        )
    else:
        print("EXPLICIT SEQUENCE IDs NOT PRESERVED")
        print()
        print(
            "We will use ordered creation instead."
        )

    print("========================================")

finally:
    # =====================================================
    # Always delete temporary project
    # =====================================================

    if project_id:
        print()
        print("Deleting temporary project...")

        try:
            request(
                "DELETE",
                (
                    f"/api/v1/workspaces/"
                    f"{PLANE_WORKSPACE_SLUG}/projects/"
                    f"{project_id}/"
                ),
            )

            print(
                "Temporary project deleted successfully."
            )

        except Exception as exc:
            print(
                "WARNING: Could not delete temporary project:"
            )
            print(exc)
            print()
            print(
                "Delete 'Migration Sequence Test' manually "
                "from Plane."
            )


print()
print("HOR project was never touched.")