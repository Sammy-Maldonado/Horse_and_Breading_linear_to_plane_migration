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
# Load newest Linear backup
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
# Load Linear -> Plane work-item mapping
# =========================================================

work_item_mapping_path = (
    backup_dir
    / "linear_to_plane_mapping.json"
)

if not work_item_mapping_path.exists():
    raise RuntimeError(
        "linear_to_plane_mapping.json not found"
    )

with work_item_mapping_path.open(
    "r",
    encoding="utf-8",
) as file:
    work_item_mapping = json.load(file)


if len(work_item_mapping) != 220:
    raise RuntimeError(
        f"Expected 220 work-item mappings, "
        f"found {len(work_item_mapping)}"
    )


# =========================================================
# Comment migration mapping
# =========================================================

comment_mapping_path = (
    backup_dir
    / "linear_to_plane_comment_mapping.json"
)

if comment_mapping_path.exists():
    with comment_mapping_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        comment_mapping = json.load(file)
else:
    comment_mapping = {}


def save_comment_mapping():
    with comment_mapping_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            comment_mapping,
            file,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# Markdown cleanup
# =========================================================

LINEAR_ISSUE_TAG = re.compile(
    r'<issue\b[^>]*>\s*(HOR-\d+)\s*</issue>',
    flags=re.IGNORECASE,
)


LINEAR_MARKDOWN_ISSUE_LINK = re.compile(
    r'\[([^\]]+)\]'
    r'\('
    r'https://linear\.app/[^)\s]*/issue/(HOR-\d+)'
    r'[^)]*'
    r'\)',
    flags=re.IGNORECASE,
)


LINEAR_RAW_ISSUE_URL = re.compile(
    r'https://linear\.app/'
    r'[^\s<>"\')]*'
    r'/issue/'
    r'(HOR-\d+)'
    r'[^\s<>"\')]*',
    flags=re.IGNORECASE,
)


def clean_linear_markdown(text):
    if not text:
        return ""

    # Linear rich-text issue reference:
    #
    # <issue ...>HOR-13</issue>
    #
    # becomes:
    #
    # HOR-13

    text = LINEAR_ISSUE_TAG.sub(
        lambda match: match.group(1),
        text,
    )

    # Markdown link pointing at Linear issue:
    #
    # [HOR-13](https://linear.app/.../HOR-13/...)
    #
    # becomes visible text only.

    text = LINEAR_MARKDOWN_ISSUE_LINK.sub(
        lambda match: match.group(1),
        text,
    )

    # Raw Linear issue URL:
    #
    # https://linear.app/.../issue/HOR-13/...
    #
    # becomes:
    #
    # HOR-13

    text = LINEAR_RAW_ISSUE_URL.sub(
        lambda match: match.group(1),
        text,
    )

    return text


def markdown_to_html(text):
    cleaned = clean_linear_markdown(
        text or ""
    )

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
# Comment HTML
# =========================================================

def build_comment_html(comment):
    user = comment.get("user") or {}

    author = (
        user.get("name")
        or user.get("email")
        or "Unknown Linear user"
    )

    created_at = (
        comment.get("createdAt")
        or "unknown"
    )

    updated_at = comment.get(
        "updatedAt"
    )

    resolved_at = comment.get(
        "resolvedAt"
    )

    archived_at = comment.get(
        "archivedAt"
    )

    metadata_parts = [
        "Migrated from Linear",
        (
            "Original author: "
            f"{html.escape(author)}"
        ),
        (
            "Original created: "
            f"{html.escape(created_at)}"
        ),
    ]

    if (
        updated_at
        and updated_at != created_at
    ):
        metadata_parts.append(
            "Original updated: "
            f"{html.escape(updated_at)}"
        )

    if resolved_at:
        metadata_parts.append(
            "Original resolved: "
            f"{html.escape(resolved_at)}"
        )

    if archived_at:
        metadata_parts.append(
            "Original archived: "
            f"{html.escape(archived_at)}"
        )

    metadata_html = (
        "<p><em>"
        + " · ".join(metadata_parts)
        + "</em></p>"
    )

    quoted_text = comment.get(
        "quotedText"
    )

    quoted_html = ""

    if quoted_text:
        quoted_html = (
            "<blockquote>"
            "<p><strong>"
            "Original Linear inline anchor:"
            "</strong></p>"
            "<p>"
            + html.escape(quoted_text)
            + "</p>"
            "</blockquote>"
        )

    body_html = markdown_to_html(
        comment.get("body") or ""
    )

    if not body_html:
        body_html = "<p></p>"

    return (
        metadata_html
        + quoted_html
        + body_html
    )


# =========================================================
# Plane comment paths
# =========================================================

def comments_path(plane_work_item_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_work_item_id}/comments/"
    )


# =========================================================
# Retrieve existing Plane comments
# =========================================================

def get_existing_comments(
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
            comments_path(
                plane_work_item_id
            ),
            params=params,
        )

        # Some versions may respond as a list.
        if isinstance(data, list):
            results.extend(data)
            break

        page_results = data.get(
            "results",
            [],
        )

        results.extend(
            page_results
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
# Source comment inventory
# =========================================================

source_comment_ids = set()

source_comment_count = 0
source_reply_count = 0


for issue in issues:
    for comment in issue.get(
        "comments",
        [],
    ):
        comment_id = comment["id"]

        if comment_id in source_comment_ids:
            raise RuntimeError(
                f"Duplicate Linear comment ID: "
                f"{comment_id}"
            )

        source_comment_ids.add(
            comment_id
        )

        source_comment_count += 1

        if comment.get("parent"):
            source_reply_count += 1


print("========================================")
print("PLANE COMMENT IMPORT")
print("========================================")
print()

print(
    "Linear comments:",
    source_comment_count,
)

print(
    "Linear replies:",
    source_reply_count,
)

print()

if source_comment_count != 475:
    raise RuntimeError(
        f"Expected 475 comments, "
        f"found {source_comment_count}"
    )

if source_reply_count != 3:
    raise RuntimeError(
        f"Expected 3 replies, "
        f"found {source_reply_count}"
    )


# =========================================================
# Import
# =========================================================

created_count = 0
existing_count = 0
reply_count = 0

issues_with_comments = 0


def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


issues.sort(
    key=issue_number
)


for issue in issues:
    comments = issue.get(
        "comments",
        [],
    )

    if not comments:
        continue

    issues_with_comments += 1

    identifier = issue[
        "identifier"
    ]

    plane_work_item_id = (
        work_item_mapping[
            identifier
        ]["plane_id"]
    )

    print()
    print(
        f"{identifier} "
        f"({len(comments)} comments)"
    )

    # -----------------------------------------------------
    # Recover existing imported comments from Plane
    # -----------------------------------------------------

    existing_plane_comments = (
        get_existing_comments(
            plane_work_item_id
        )
    )

    for plane_comment in (
        existing_plane_comments
    ):
        external_source = (
            plane_comment.get(
                "external_source"
            )
        )

        external_id = (
            plane_comment.get(
                "external_id"
            )
        )

        if (
            external_source == "linear"
            and external_id
        ):
            if (
                external_id
                in source_comment_ids
            ):
                comment_mapping[
                    external_id
                ] = {
                    "plane_id": (
                        plane_comment["id"]
                    ),
                    "issue": identifier,
                }

    save_comment_mapping()

    # -----------------------------------------------------
    # Oldest first
    # -----------------------------------------------------

    pending = sorted(
        comments,
        key=lambda comment: (
            comment.get("createdAt")
            or ""
        ),
    )

    # -----------------------------------------------------
    # Process until all parent dependencies are satisfied
    # -----------------------------------------------------

    while pending:
        progress = False
        remaining = []

        for comment in pending:
            linear_comment_id = (
                comment["id"]
            )

            # ---------------------------------------------
            # Already imported
            # ---------------------------------------------

            if (
                linear_comment_id
                in comment_mapping
            ):
                existing_count += 1

                print(
                    "  "
                    f"{linear_comment_id[:8]}"
                    " -> already exists ✓"
                )

                progress = True
                continue

            # ---------------------------------------------
            # Parent comment, if this is a reply
            # ---------------------------------------------

            parent = comment.get(
                "parent"
            )

            linear_parent_id = None
            plane_parent_id = None

            if parent:
                linear_parent_id = (
                    parent.get("id")
                )

                if (
                    linear_parent_id
                    not in comment_mapping
                ):
                    # Parent not imported yet.
                    # Try again in the next pass.
                    remaining.append(
                        comment
                    )
                    continue

                plane_parent_id = (
                    comment_mapping[
                        linear_parent_id
                    ]["plane_id"]
                )

            # ---------------------------------------------
            # Create Plane comment
            # ---------------------------------------------

            payload = {
                "comment_html": (
                    build_comment_html(
                        comment
                    )
                ),
                "access": "INTERNAL",
                "external_source": (
                    "linear"
                ),
                "external_id": (
                    linear_comment_id
                ),
            }

            if plane_parent_id:
                payload["parent"] = (
                    plane_parent_id
                )

            created = request(
                "POST",
                comments_path(
                    plane_work_item_id
                ),
                json=payload,
            )

            plane_comment_id = (
                created["id"]
            )

            comment_mapping[
                linear_comment_id
            ] = {
                "plane_id": (
                    plane_comment_id
                ),
                "issue": identifier,
                "linear_parent_id": (
                    linear_parent_id
                ),
            }

            # Save after EVERY successful comment.
            # This makes the importer resumable.
            save_comment_mapping()

            created_count += 1

            if linear_parent_id:
                reply_count += 1

                print(
                    "  "
                    f"{linear_comment_id[:8]}"
                    " -> reply created ✓"
                )
            else:
                print(
                    "  "
                    f"{linear_comment_id[:8]}"
                    " -> created ✓"
                )

            progress = True

        if not progress:
            unresolved = [
                {
                    "comment": c["id"],
                    "parent": (
                        (
                            c.get("parent")
                            or {}
                        ).get("id")
                    ),
                }
                for c in remaining
            ]

            raise RuntimeError(
                "Could not resolve comment "
                "parent relationships:\n"
                + json.dumps(
                    unresolved,
                    indent=2,
                )
            )

        pending = remaining


# =========================================================
# Final structural validation
# =========================================================

mapped_source_ids = (
    set(comment_mapping.keys())
    & source_comment_ids
)

missing_comment_ids = (
    source_comment_ids
    - mapped_source_ids
)


print()
print("========================================")
print("COMMENT IMPORT VALIDATION")
print("========================================")

print(
    "Source comments:",
    source_comment_count,
)

print(
    "Mapped comments:",
    len(mapped_source_ids),
)

print(
    "Issues containing comments:",
    issues_with_comments,
)

print(
    "Created this run:",
    created_count,
)

print(
    "Already existing:",
    existing_count,
)

print(
    "Replies created this run:",
    reply_count,
)


if missing_comment_ids:
    print()
    print("VALIDATION FAILED")

    for comment_id in sorted(
        missing_comment_ids
    ):
        print(
            "Missing:",
            comment_id,
        )

    raise SystemExit(1)


# Validate that all three source replies
# have a mapped parent.

reply_validation_count = 0

for issue in issues:
    for comment in issue.get(
        "comments",
        [],
    ):
        parent = comment.get(
            "parent"
        )

        if not parent:
            continue

        parent_id = parent.get(
            "id"
        )

        if (
            parent_id
            not in comment_mapping
        ):
            raise RuntimeError(
                f"Reply {comment['id']} "
                f"is missing mapped parent "
                f"{parent_id}"
            )

        reply_validation_count += 1


if (
    reply_validation_count
    != source_reply_count
):
    raise RuntimeError(
        "Reply validation count mismatch"
    )


print()
print("========================================")
print("COMMENT IMPORT COMPLETE")
print("========================================")

print(
    "All 475 Linear comments mapped: YES"
)

print(
    "All 3 reply relationships mapped: YES"
)

print()

print(
    "Mapping:",
    comment_mapping_path,
)

print()

print(
    "Labels, GitHub links and issue "
    "relations have NOT been migrated yet."
)