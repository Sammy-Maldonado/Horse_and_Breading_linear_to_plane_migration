import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

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

with backup_path.open(
    "r",
    encoding="utf-8",
) as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Load work-item mapping
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
# Link mapping
# =========================================================

link_mapping_path = (
    backup_dir
    / "linear_to_plane_link_mapping.json"
)

if link_mapping_path.exists():
    with link_mapping_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        link_mapping = json.load(file)
else:
    link_mapping = {}


def save_link_mapping():
    with link_mapping_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            link_mapping,
            file,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# Source helpers
# =========================================================

def extract_attachments(issue):
    attachments = (
        issue.get("attachments")
        or []
    )

    if isinstance(attachments, list):
        return attachments

    if isinstance(attachments, dict):
        for key in (
            "nodes",
            "results",
            "data",
        ):
            value = attachments.get(key)

            if isinstance(value, list):
                return value

    return []


def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


def normalize_title(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_url(value):
    if value is None:
        return ""

    return str(value).strip()


issues.sort(key=issue_number)


# =========================================================
# Build source inventory
# =========================================================

source_attachments = {}
issue_attachments = {}

all_urls = []


for issue in issues:
    identifier = issue["identifier"]

    attachments = extract_attachments(
        issue
    )

    normalized = []

    for attachment in attachments:
        attachment_id = attachment.get("id")

        url = normalize_url(
            attachment.get("url")
        )

        title = normalize_title(
            attachment.get("title")
        )

        if not attachment_id:
            raise RuntimeError(
                f"{identifier}: attachment "
                "without ID"
            )

        if not url:
            raise RuntimeError(
                f"{identifier}: attachment "
                f"{attachment_id} without URL"
            )

        if attachment_id in source_attachments:
            raise RuntimeError(
                f"Duplicate Linear attachment ID: "
                f"{attachment_id}"
            )

        parsed = urlparse(url)

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        if hostname not in {
            "github.com",
            "www.github.com",
        }:
            raise RuntimeError(
                f"{identifier}: expected GitHub "
                f"URL but found:\n{url}"
            )

        if len(title) > 255:
            raise RuntimeError(
                f"{identifier}: link title exceeds "
                f"255 characters:\n{title}"
            )

        record = {
            "id": attachment_id,
            "issue": identifier,
            "url": url,
            "title": title,
        }

        source_attachments[
            attachment_id
        ] = record

        normalized.append(record)

        all_urls.append(url)

    issue_attachments[
        identifier
    ] = normalized


# =========================================================
# Pre-flight
# =========================================================

source_count = len(
    source_attachments
)

unique_urls = len(
    set(all_urls)
)

issues_with_links = sum(
    1
    for attachments
    in issue_attachments.values()
    if attachments
)


print("========================================")
print("PLANE GITHUB LINK IMPORT")
print("========================================")
print()

print(
    "Source attachment rows:",
    source_count,
)

print(
    "Unique URLs:",
    unique_urls,
)

print(
    "Work items with GitHub links:",
    issues_with_links,
)

print()


if source_count != 457:
    raise RuntimeError(
        f"Expected 457 attachment rows, "
        f"found {source_count}"
    )


if unique_urls != 428:
    raise RuntimeError(
        f"Expected 428 unique URLs, "
        f"found {unique_urls}"
    )


print("Pre-flight validation: OK")
print()


# =========================================================
# Plane link helpers
# =========================================================

def links_path(plane_work_item_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_work_item_id}/links/"
    )


def get_plane_links(
    plane_work_item_id,
):
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
            links_path(
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


def plane_signature(link):
    return (
        normalize_url(
            link.get("url")
        ),
        normalize_title(
            link.get("title")
        ),
    )


def source_signature(record):
    return (
        record["url"],
        record["title"],
    )


# =========================================================
# Import
# =========================================================

created_count = 0
recovered_count = 0
already_mapped_count = 0


for issue in issues:
    identifier = issue[
        "identifier"
    ]

    attachments = issue_attachments[
        identifier
    ]

    if not attachments:
        continue

    plane_work_item_id = (
        work_mapping[
            identifier
        ]["plane_id"]
    )

    print()
    print(
        f"{identifier} "
        f"({len(attachments)} links)"
    )

    existing_links = (
        get_plane_links(
            plane_work_item_id
        )
    )

    existing_by_id = {
        link["id"]: link
        for link in existing_links
    }

    claimed_plane_ids = set()

    # -----------------------------------------------------
    # Validate mappings that already exist
    # -----------------------------------------------------

    for attachment in attachments:
        attachment_id = attachment["id"]

        mapping = link_mapping.get(
            attachment_id
        )

        if not mapping:
            continue

        plane_link_id = mapping.get(
            "plane_id"
        )

        plane_link = existing_by_id.get(
            plane_link_id
        )

        if plane_link is None:
            raise RuntimeError(
                f"{identifier}: mapped Plane "
                f"link {plane_link_id} no longer "
                f"exists for Linear attachment "
                f"{attachment_id}"
            )

        if (
            plane_signature(plane_link)
            != source_signature(attachment)
        ):
            raise RuntimeError(
                f"{identifier}: mapped link "
                "does not match source.\n"
                f"Linear: "
                f"{source_signature(attachment)}\n"
                f"Plane: "
                f"{plane_signature(plane_link)}"
            )

        claimed_plane_ids.add(
            plane_link_id
        )

    # -----------------------------------------------------
    # Import / recover
    # -----------------------------------------------------

    for attachment in attachments:
        attachment_id = attachment[
            "id"
        ]

        if attachment_id in link_mapping:
            already_mapped_count += 1

            print(
                "  "
                f"{attachment_id[:8]}"
                " -> already mapped ✓"
            )

            continue

        wanted_signature = (
            source_signature(
                attachment
            )
        )

        # ---------------------------------------------
        # Recovery:
        # maybe POST succeeded during a previous run
        # but the script stopped before saving mapping.
        # ---------------------------------------------

        recovered = None

        for plane_link in existing_links:
            plane_link_id = (
                plane_link["id"]
            )

            if (
                plane_link_id
                in claimed_plane_ids
            ):
                continue

            if (
                plane_signature(
                    plane_link
                )
                == wanted_signature
            ):
                recovered = plane_link
                break

        if recovered is not None:
            plane_link_id = (
                recovered["id"]
            )

            link_mapping[
                attachment_id
            ] = {
                "plane_id": plane_link_id,
                "issue": identifier,
                "url": attachment["url"],
                "title": attachment[
                    "title"
                ],
            }

            claimed_plane_ids.add(
                plane_link_id
            )

            save_link_mapping()

            recovered_count += 1

            print(
                "  "
                f"{attachment_id[:8]}"
                " -> recovered existing ✓"
            )

            continue

        # ---------------------------------------------
        # Create Plane link
        # ---------------------------------------------

        payload = {
            "url": attachment["url"],
        }

        if attachment["title"]:
            payload["title"] = (
                attachment["title"]
            )

        created = request(
            "POST",
            links_path(
                plane_work_item_id
            ),
            json=payload,
        )

        plane_link_id = created[
            "id"
        ]

        created_signature = (
            plane_signature(created)
        )

        if (
            created_signature
            != wanted_signature
        ):
            raise RuntimeError(
                f"{identifier}: Plane created "
                f"unexpected link data.\n"
                f"Expected: "
                f"{wanted_signature}\n"
                f"Returned: "
                f"{created_signature}"
            )

        link_mapping[
            attachment_id
        ] = {
            "plane_id": plane_link_id,
            "issue": identifier,
            "url": attachment["url"],
            "title": attachment[
                "title"
            ],
        }

        claimed_plane_ids.add(
            plane_link_id
        )

        existing_links.append(
            created
        )

        existing_by_id[
            plane_link_id
        ] = created

        # Save after every successful POST
        save_link_mapping()

        created_count += 1

        print(
            "  "
            f"{attachment_id[:8]}"
            " -> created ✓"
        )


# =========================================================
# Mapping validation
# =========================================================

source_ids = set(
    source_attachments.keys()
)

mapped_source_ids = (
    set(link_mapping.keys())
    & source_ids
)

missing_ids = (
    source_ids
    - mapped_source_ids
)


print()
print("========================================")
print("GITHUB LINK MAPPING VALIDATION")
print("========================================")

print(
    "Source rows:",
    source_count,
)

print(
    "Mapped rows:",
    len(mapped_source_ids),
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


if missing_ids:
    print()
    print("VALIDATION FAILED")

    for attachment_id in sorted(
        missing_ids
    ):
        print(
            "Missing:",
            attachment_id,
        )

    raise SystemExit(1)


# =========================================================
# Final Plane verification
# =========================================================

print()
print("Verifying links in Plane...")

verified_count = 0


for issue in issues:
    identifier = issue[
        "identifier"
    ]

    attachments = issue_attachments[
        identifier
    ]

    if not attachments:
        continue

    plane_work_item_id = (
        work_mapping[
            identifier
        ]["plane_id"]
    )

    plane_links = get_plane_links(
        plane_work_item_id
    )

    plane_links_by_id = {
        link["id"]: link
        for link in plane_links
    }

    for attachment in attachments:
        attachment_id = attachment[
            "id"
        ]

        mapping = link_mapping[
            attachment_id
        ]

        plane_link_id = mapping[
            "plane_id"
        ]

        plane_link = (
            plane_links_by_id.get(
                plane_link_id
            )
        )

        if plane_link is None:
            raise RuntimeError(
                f"{identifier}: Plane link "
                f"{plane_link_id} missing"
            )

        if (
            plane_signature(plane_link)
            != source_signature(
                attachment
            )
        ):
            raise RuntimeError(
                f"{identifier}: final link "
                f"verification failed for "
                f"{attachment_id}"
            )

        verified_count += 1


if verified_count != 457:
    raise RuntimeError(
        f"Expected 457 verified links, "
        f"got {verified_count}"
    )


# =========================================================
# Final report
# =========================================================

print()
print("========================================")
print("GITHUB LINK IMPORT COMPLETE")
print("========================================")

print(
    "Source attachment rows:",
    source_count,
)

print(
    "Unique GitHub URLs:",
    unique_urls,
)

print(
    "Mapped links:",
    len(mapped_source_ids),
)

print(
    "Verified in Plane:",
    verified_count,
)

print()

print(
    "Mapping:",
    link_mapping_path,
)

print()

print(
    "Issue relations have NOT been "
    "migrated yet."
)