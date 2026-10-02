import os
from pathlib import Path

import requests
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

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
}


def get(path):
    url = f"{PLANE_BASE_URL}{path}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    print(f"GET {path}")
    print("Status:", response.status_code)

    if not response.ok:
        print(response.text)
        raise SystemExit(1)

    return response.json()


# =========================================================
# States
# =========================================================

states_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
    f"{PLANE_PROJECT_ID}/states/"
)

states_data = get(states_path)

states = states_data.get(
    "results",
    states_data if isinstance(states_data, list) else [],
)

print()
print("========================================")
print("PLANE STATES")
print("========================================")

for state in states:
    print(
        f"{state.get('name')} "
        f"| group={state.get('group')} "
        f"| id={state.get('id')}"
    )


# =========================================================
# Work items
# =========================================================

items_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
    f"{PLANE_PROJECT_ID}/work-items/"
)

items_data = get(items_path)

if isinstance(items_data, dict):
    items = items_data.get("results", [])

    total = items_data.get(
        "total_results",
        items_data.get(
            "total_count",
            len(items),
        ),
    )
else:
    items = items_data
    total = len(items)


print()
print("========================================")
print("PLANE PROJECT")
print("========================================")

print("Work items:", total)

if total == 0:
    print("Project is clean: YES")
else:
    print("Project is clean: NO")

    for item in items:
        print(
            item.get("sequence_id"),
            item.get("name"),
        )


print()
print("No data was modified.")