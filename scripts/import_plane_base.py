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


# =========================================================
# Rate limit configuration
# =========================================================

REQUEST_DELAY_SECONDS = 1.2
MAX_RATE_LIMIT_RETRIES = 10


# =========================================================
# Load migration plan
# =========================================================

plan_path = BACKUP_DIR / "plane_migration_plan.json"

if not plan_path.exists():
    raise RuntimeError(
        "backups/plane_migration_plan.json not found"
    )

with plan_path.open("r", encoding="utf-8") as file:
    plan = json.load(file)

issues = plan["issues"]

if len(issues) != 220:
    raise RuntimeError(
        f"Expected 220 issues, found {len(issues)}"
    )


# =========================================================
# HTTP helper
# =========================================================

def request(method, path, allow_404=False, **kwargs):
    url = f"{PLANE_BASE_URL}{path}"

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        response = requests.request(
            method,
            url,
            headers=HEADERS,
            timeout=30,
            **kwargs,
        )

        # -------------------------------------------------
        # Plane rate limit
        # -------------------------------------------------

        if response.status_code == 429:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                print()
                print(
                    "Rate limit retry limit reached."
                )
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

        # -------------------------------------------------
        # Pace successful/non-rate-limited requests
        # -------------------------------------------------

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

        # -------------------------------------------------
        # Optional 404
        # -------------------------------------------------

        if (
            allow_404
            and response.status_code == 404
        ):
            return None

        # -------------------------------------------------
        # Other errors
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Empty response
        # -------------------------------------------------

        if response.status_code == 204:
            return None

        return response.json()

    raise RuntimeError(
        "Unexpected Plane API retry failure"
    )


# =========================================================
# Fetch Plane states dynamically
# =========================================================

states_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
    f"{PLANE_PROJECT_ID}/states/"
)

states_data = request(
    "GET",
    states_path,
)

states = states_data.get(
    "results",
    states_data
    if isinstance(states_data, list)
    else [],
)

state_ids = {
    state["name"]: state["id"]
    for state in states
}

required_states = {
    "Backlog",
    "Todo",
    "In Progress",
    "Done",
    "Cancelled",
}

missing_states = (
    required_states - set(state_ids)
)

if missing_states:
    raise RuntimeError(
        f"Missing Plane states: "
        f"{sorted(missing_states)}"
    )


# =========================================================
# Pre-flight validation
# =========================================================

print("========================================")
print("PLANE BASE IMPORT")
print("========================================")
print()

print("Pre-flight validation...")


for expected, issue in enumerate(
    issues,
    start=1,
):
    if (
        issue["expected_sequence_id"]
        != expected
    ):
        raise RuntimeError(
            f"Migration plan sequence mismatch "
            f"at {expected}"
        )

    expected_identifier = (
        f"HOR-{expected}"
    )

    if (
        issue["linear_identifier"]
        != expected_identifier
    ):
        raise RuntimeError(
            f"Expected {expected_identifier}, "
            f"found "
            f"{issue['linear_identifier']}"
        )

    if len(issue["name"]) > 255:
        raise RuntimeError(
            f"{issue['linear_identifier']} title "
            f"is longer than 255 characters"
        )

    if issue["state"] not in state_ids:
        raise RuntimeError(
            f"{issue['linear_identifier']} has "
            f"unknown state "
            f"{issue['state']}"
        )


print("Migration plan: OK")
print("States: OK")
print("Titles: OK")
print()


# =========================================================
# API paths
# =========================================================

create_path = (
    f"/api/v1/workspaces/"
    f"{PLANE_WORKSPACE_SLUG}/projects/"
    f"{PLANE_PROJECT_ID}/work-items/"
)


def identifier_path(identifier):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/work-items/"
        f"{identifier}/"
    )


# =========================================================
# Import
# =========================================================

mapping = {}

created_count = 0
existing_count = 0


for index, issue in enumerate(
    issues,
    start=1,
):
    identifier = (
        issue["linear_identifier"]
    )

    expected_sequence = (
        issue["expected_sequence_id"]
    )

    print(
        f"[{index:03}/220] "
        f"{identifier}",
        end="",
        flush=True,
    )

    # =====================================================
    # Resume-safe check
    # =====================================================

    existing = request(
        "GET",
        identifier_path(identifier),
        allow_404=True,
    )

    if existing is not None:
        returned_sequence = (
            existing.get("sequence_id")
        )

        returned_name = (
            existing.get("name")
        )

        if (
            returned_sequence
            != expected_sequence
        ):
            raise RuntimeError(
                f"\n{identifier}: existing "
                f"Plane item has "
                f"sequence_id="
                f"{returned_sequence}, "
                f"expected "
                f"{expected_sequence}"
            )

        if (
            returned_name
            != issue["name"]
        ):
            raise RuntimeError(
                f"\n{identifier}: "
                f"title mismatch.\n"
                f"Plane:  "
                f"{returned_name}\n"
                f"Linear: "
                f"{issue['name']}"
            )

        mapping[identifier] = {
            "linear_uuid": (
                issue["linear_uuid"]
            ),
            "plane_id": (
                existing["id"]
            ),
            "sequence_id": (
                returned_sequence
            ),
        }

        existing_count += 1

        print(
            " -> already exists ✓"
        )

        continue

    # =====================================================
    # Create work item
    # =====================================================

    payload = {
        "name": issue["name"],
        "priority": (
            issue["priority"]
        ),
        "state": state_ids[
            issue["state"]
        ],
        "external_source": "linear",
        "external_id": (
            issue["linear_uuid"]
        ),
    }

    created = request(
        "POST",
        create_path,
        json=payload,
    )

    returned_sequence = (
        created.get("sequence_id")
    )

    # =====================================================
    # Critical sequence validation
    # =====================================================

    if (
        returned_sequence
        != expected_sequence
    ):
        raise RuntimeError(
            f"\nCRITICAL SEQUENCE MISMATCH\n"
            f"Linear: {identifier}\n"
            f"Expected Plane sequence: "
            f"{expected_sequence}\n"
            f"Plane returned: "
            f"{returned_sequence}\n\n"
            f"IMPORT STOPPED."
        )

    plane_identifier = (
        f"HOR-{returned_sequence}"
    )

    if (
        plane_identifier
        != identifier
    ):
        raise RuntimeError(
            f"\nIdentifier mismatch: "
            f"{plane_identifier} "
            f"!= {identifier}"
        )

    mapping[identifier] = {
        "linear_uuid": (
            issue["linear_uuid"]
        ),
        "plane_id": (
            created["id"]
        ),
        "sequence_id": (
            returned_sequence
        ),
    }

    created_count += 1

    print(" -> created ✓")


# =========================================================
# Save Linear -> Plane mapping
# =========================================================

mapping_path = (
    BACKUP_DIR
    / "linear_to_plane_mapping.json"
)

with mapping_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        mapping,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Final verification
# =========================================================

print()
print(
    "Verifying all HOR identifiers..."
)

for expected in range(1, 221):
    identifier = f"HOR-{expected}"

    item = request(
        "GET",
        identifier_path(identifier),
    )

    returned_sequence = (
        item.get("sequence_id")
    )

    if returned_sequence != expected:
        raise RuntimeError(
            f"{identifier}: final sequence "
            f"verification failed. "
            f"Returned "
            f"{returned_sequence}"
        )


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("BASE IMPORT COMPLETE")
print("========================================")

print(
    "Created:",
    created_count,
)

print(
    "Already existing:",
    existing_count,
)

print(
    "Total verified:",
    len(mapping),
)

print()

print(
    "Mapping:",
    mapping_path,
)

print()

print(
    "HOR-1 -> HOR-220 preserved exactly."
)

print()

print(
    "Descriptions, hierarchy, comments, "
    "labels and relations have NOT been "
    "migrated yet."
)