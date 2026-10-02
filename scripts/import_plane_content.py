import html
import json
import os
import re
import time
from pathlib import Path

import markdown
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

    raise RuntimeError("Unexpected Plane API retry failure")


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
# Load Linear -> Plane mapping
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
    mapping = json.load(file)


if len(mapping) != 220:
    raise RuntimeError(
        f"Expected mapping for 220 issues, "
        f"found {len(mapping)}"
    )


# =========================================================
# Helpers
# =========================================================

def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


issues.sort(key=issue_number)


# Linear sometimes returns references like:
#
# <issue id="..." href="https://linear.app/...">
# HOR-13
# </issue>
#
# Plane does not understand that custom tag.
LINEAR_ISSUE_TAG = re.compile(
    r'<issue\b[^>]*>\s*(HOR-\d+)\s*</issue>',
    flags=re.IGNORECASE,
)


# Markdown link pointing specifically at a Linear issue.
LINEAR_MARKDOWN_ISSUE_LINK = re.compile(
    r'\[([^\]]+)\]'
    r'\('
    r'https://linear\.app/[^)\s]*/issue/(HOR-\d+)'
    r'[^)]*'
    r'\)',
    flags=re.IGNORECASE,
)


def clean_linear_markdown(text):
    if not text:
        return ""

    # ---------------------------------------------
    # Convert Linear custom <issue> tags
    # to their durable HOR identifier.
    # ---------------------------------------------

    text = LINEAR_ISSUE_TAG.sub(
        lambda match: match.group(1),
        text,
    )

    # ---------------------------------------------
    # Remove stale Linear issue hyperlinks while
    # preserving their visible text.
    #
    # [HOR-13](https://linear.app/.../HOR-13/...)
    # becomes:
    # HOR-13
    # ---------------------------------------------

    text = LINEAR_MARKDOWN_ISSUE_LINK.sub(
        lambda match: match.group(1),
        text,
    )

    return text


def markdown_to_html(text):
    cleaned = clean_linear_markdown(text)

    if not cleaned.strip():
        return ""

    return markdown.markdown(
        cleaned,
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
        ],
        output_format="html5",
    )


# =========================================================
# Pre-flight validation
# =========================================================

print("========================================")
print("PLANE CONTENT IMPORT")
print("========================================")
print()

print("Pre-flight validation...")


known_identifiers = {
    issue["identifier"]
    for issue in issues
}


for expected, issue in enumerate(
    issues,
    start=1,
):
    identifier = issue["identifier"]

    if identifier != f"HOR-{expected}":
        raise RuntimeError(
            f"Expected HOR-{expected}, "
            f"found {identifier}"
        )

    if identifier not in mapping:
        raise RuntimeError(
            f"{identifier} missing from Plane mapping"
        )

    parent = issue.get("parent")

    if parent:
        parent_identifier = parent.get("identifier")

        if parent_identifier not in known_identifiers:
            raise RuntimeError(
                f"{identifier} references unknown "
                f"parent {parent_identifier}"
            )

        if parent_identifier not in mapping:
            raise RuntimeError(
                f"{identifier} parent "
                f"{parent_identifier} missing "
                f"from Plane mapping"
            )


print("220 mappings: OK")
print("Parent references: OK")
print()


# =========================================================
# Import descriptions + parents
# =========================================================

description_count = 0
parent_count = 0
updated_count = 0


for index, issue in enumerate(
    issues,
    start=1,
):
    identifier = issue["identifier"]

    plane_id = mapping[
        identifier
    ]["plane_id"]

    payload = {}

    # =====================================================
    # Description
    # =====================================================

    description = issue.get("description") or ""

    if description.strip():
        payload["description_html"] = (
            markdown_to_html(description)
        )

        description_count += 1

    # =====================================================
    # Parent
    # =====================================================

    parent = issue.get("parent")

    if parent:
        parent_identifier = (
            parent["identifier"]
        )

        parent_plane_id = mapping[
            parent_identifier
        ]["plane_id"]

        payload["parent"] = (
            parent_plane_id
        )

        parent_count += 1

    # =====================================================
    # Nothing to update
    # =====================================================

    if not payload:
        print(
            f"[{index:03}/220] "
            f"{identifier} -> nothing to update"
        )

        continue

    # =====================================================
    # PATCH work item
    # =====================================================

    update_path = (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_id}/"
    )

    request(
        "PATCH",
        update_path,
        json=payload,
    )

    updated_count += 1

    parts = []

    if "description_html" in payload:
        parts.append("description")

    if "parent" in payload:
        parts.append("parent")

    print(
        f"[{index:03}/220] "
        f"{identifier} -> "
        f"{' + '.join(parts)} ✓"
    )


# =========================================================
# Read-only verification
# =========================================================

print()
print("Verifying HOR-1 -> HOR-220...")

verified_count = 0


def identifier_path(identifier):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/work-items/"
        f"{identifier}/"
    )


for expected, issue in enumerate(
    issues,
    start=1,
):
    identifier = issue["identifier"]

    item = request(
        "GET",
        identifier_path(identifier),
    )

    if item.get("sequence_id") != expected:
        raise RuntimeError(
            f"{identifier}: sequence changed. "
            f"Expected {expected}, "
            f"got {item.get('sequence_id')}"
        )

    if item.get("name") != issue["title"]:
        raise RuntimeError(
            f"{identifier}: title changed unexpectedly"
        )

    verified_count += 1


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("CONTENT IMPORT COMPLETE")
print("========================================")

print(
    "Work items updated:",
    updated_count,
)

print(
    "Descriptions migrated:",
    description_count,
)

print(
    "Parent relationships migrated:",
    parent_count,
)

print(
    "HOR identifiers verified:",
    verified_count,
)

print()

print(
    "HOR-1 -> HOR-220 numbering remains intact."
)

print()

print(
    "Comments, labels, issue relations and "
    "GitHub attachments have NOT been migrated yet."
)