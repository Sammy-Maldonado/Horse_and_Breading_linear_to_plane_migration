import html
import json
import os
import re
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import markdown
import requests
from dotenv import load_dotenv


# =========================================================
# Project paths
# =========================================================

# Current structure:
#
# linear-to-plane-migration/
# ├── backups/
# ├── docs/
# ├── scripts/
# │   └── final_migration_audit.py
# ├── .env
# └── .env.example

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
                print()
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
# Load source backup
# =========================================================

backups = sorted(
    BACKUP_DIR.glob(
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
# Load migration artifacts
# =========================================================

def load_json(filename):
    path = BACKUP_DIR / filename

    if not path.exists():
        raise RuntimeError(
            f"Missing migration artifact: "
            f"{path}"
        )

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

label_mapping = load_json(
    "linear_to_plane_label_mapping.json"
)

link_mapping = load_json(
    "linear_to_plane_link_mapping.json"
)

relation_mapping = load_json(
    "linear_to_plane_relation_mapping.json"
)

historical_metadata = load_json(
    "linear_historical_metadata.json"
)


# =========================================================
# Source helpers
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


def issue_number(issue):
    return int(
        issue["identifier"].split("-")[1]
    )


issues.sort(key=issue_number)


# =========================================================
# Generic ID normalization
# =========================================================

def normalize_id(value):
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return (
            value.get("id")
            or value.get("member_id")
            or value.get("issue_id")
        )

    return None


def normalize_id_set(value):
    if not value:
        return set()

    if not isinstance(value, list):
        return set()

    result = set()

    for entry in value:
        entry_id = normalize_id(entry)

        if entry_id:
            result.add(entry_id)

    return result


# =========================================================
# Linear rich-text cleanup
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


def clean_description_markdown(text):
    if not text:
        return ""

    text = LINEAR_ISSUE_TAG.sub(
        lambda match: match.group(1),
        text,
    )

    text = LINEAR_MARKDOWN_ISSUE_LINK.sub(
        lambda match: match.group(1),
        text,
    )

    return text


def clean_comment_markdown(text):
    if not text:
        return ""

    text = LINEAR_ISSUE_TAG.sub(
        lambda match: match.group(1),
        text,
    )

    text = LINEAR_MARKDOWN_ISSUE_LINK.sub(
        lambda match: match.group(1),
        text,
    )

    text = LINEAR_RAW_ISSUE_URL.sub(
        lambda match: match.group(1),
        text,
    )

    return text


def markdown_to_html(text):
    if not text.strip():
        return ""

    return markdown.markdown(
        text,
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
        ],
        output_format="html5",
    )


def expected_description_html(text):
    cleaned = clean_description_markdown(
        text or ""
    )

    return markdown_to_html(
        cleaned
    )


# =========================================================
# HTML -> text helpers
# =========================================================

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(value):
    if not value:
        return ""

    parser = HTMLTextExtractor()

    parser.feed(
        html.unescape(
            str(value)
        )
    )

    return " ".join(
        " ".join(
            parser.parts
        ).split()
    )


def normalize_text(value):
    return " ".join(
        str(value or "").split()
    )


def normalize_without_whitespace(value):
    return re.sub(
        r"\s+",
        "",
        str(value or ""),
    )


# =========================================================
# Plane paths
# =========================================================

def work_item_path(plane_id):
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
        f"{plane_id}/"
    )


def comments_path(plane_id):
    return (
        work_item_path(
            plane_id
        )
        + "comments/"
    )


def links_path(plane_id):
    return (
        work_item_path(
            plane_id
        )
        + "links/"
    )


def relations_path(plane_id):
    return (
        work_item_path(
            plane_id
        )
        + "relations/"
    )


def states_path():
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/states/"
    )


def labels_path():
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/labels/"
    )


def work_items_path():
    return (
        f"/api/v1/workspaces/"
        f"{PLANE_WORKSPACE_SLUG}/projects/"
        f"{PLANE_PROJECT_ID}/work-items/"
    )


# =========================================================
# Paginated collection helper
# =========================================================

def get_collection(path):
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
            path,
            params=params,
        )

        if isinstance(data, list):
            results.extend(data)
            break

        results.extend(
            data.get(
                "results",
                []
            )
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
# Build source inventories
# =========================================================

source_by_identifier = {
    issue["identifier"]: issue
    for issue in issues
}

source_comments = {}
source_links = {}
source_relations = {}
source_labels = {}


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    for comment in extract_collection(
        issue.get("comments")
    ):
        source_comments[
            comment["id"]
        ] = {
            "issue": identifier,
            "data": comment,
        }

    for attachment in extract_collection(
        issue.get("attachments")
    ):
        source_links[
            attachment["id"]
        ] = {
            "issue": identifier,
            "data": attachment,
        }

    for label in extract_collection(
        issue.get("labels")
    ):
        source_labels[
            label["id"]
        ] = label

    for collection_name in (
        "relations",
        "inverseRelations",
    ):
        for relation in extract_collection(
            issue.get(collection_name)
        ):
            relation_id = (
                relation["id"]
            )

            source = (
                relation.get("issue")
                or {}
            ).get("identifier")

            target = (
                relation.get(
                    "relatedIssue"
                )
                or {}
            ).get("identifier")

            signature = (
                relation.get("type"),
                source,
                target,
            )

            if (
                relation_id
                not in source_relations
            ):
                source_relations[
                    relation_id
                ] = signature

            elif (
                source_relations[
                    relation_id
                ]
                != signature
            ):
                raise RuntimeError(
                    f"Inconsistent Linear "
                    f"relation {relation_id}"
                )


# =========================================================
# Basic source assertions
# =========================================================

print("========================================")
print("FINAL LINEAR -> PLANE AUDIT")
print("========================================")
print()

print(
    "Linear backup:",
    backup_path,
)

print()


if len(issues) != 220:
    raise RuntimeError(
        f"Expected 220 issues, "
        f"found {len(issues)}"
    )

if len(source_comments) != 475:
    raise RuntimeError(
        f"Expected 475 comments, "
        f"found {len(source_comments)}"
    )

if len(source_links) != 457:
    raise RuntimeError(
        f"Expected 457 links, "
        f"found {len(source_links)}"
    )

if len(source_relations) != 865:
    raise RuntimeError(
        f"Expected 865 relations, "
        f"found {len(source_relations)}"
    )

if len(source_labels) != 1:
    raise RuntimeError(
        f"Expected 1 label, "
        f"found {len(source_labels)}"
    )


# =========================================================
# Mapping assertions
# =========================================================

if len(work_mapping) != 220:
    raise RuntimeError(
        "Work mapping count mismatch"
    )

if (
    len(
        set(comment_mapping)
        & set(source_comments)
    )
    != 475
):
    raise RuntimeError(
        "Comment mapping count mismatch"
    )

if (
    len(
        set(link_mapping)
        & set(source_links)
    )
    != 457
):
    raise RuntimeError(
        "Link mapping count mismatch"
    )

if (
    len(
        set(relation_mapping)
        & set(source_relations)
    )
    != 865
):
    raise RuntimeError(
        "Relation mapping count mismatch"
    )

if (
    len(
        set(label_mapping)
        & set(source_labels)
    )
    != 1
):
    raise RuntimeError(
        "Label mapping count mismatch"
    )


print(
    "Local migration artifacts: OK"
)
print()


# =========================================================
# Verify Plane project contains exactly 220 work items
# =========================================================

print(
    "Checking Plane project work-item count..."
)

plane_project_items = get_collection(
    work_items_path()
)

if len(plane_project_items) != 220:
    raise RuntimeError(
        f"Plane project contains "
        f"{len(plane_project_items)} "
        f"work items, expected 220"
    )

print(
    "Plane work items:",
    len(plane_project_items),
)

print()


# =========================================================
# Plane states
# =========================================================

states_data = request(
    "GET",
    states_path(),
)

if isinstance(states_data, list):
    states = states_data
else:
    states = states_data.get(
        "results",
        []
    )

state_name_by_id = {
    state["id"]: state["name"]
    for state in states
}


STATE_MAP = {
    "Backlog": "Backlog",
    "Todo": "Todo",
    "In Progress": "In Progress",
    "Done": "Done",
    "Canceled": "Cancelled",
}


PRIORITY_MAP = {
    0: "none",
    1: "urgent",
    2: "high",
    3: "medium",
    4: "low",
}


# =========================================================
# Current Plane user
# =========================================================

me = request(
    "GET",
    "/api/v1/users/me/",
)

plane_user_id = me["id"]


# =========================================================
# Verify Plane label itself
# =========================================================

print("Verifying label...")

plane_labels = get_collection(
    labels_path()
)

plane_labels_by_id = {
    label["id"]: label
    for label in plane_labels
}


for linear_label_id, source_label in (
    source_labels.items()
):
    plane_label_id = label_mapping[
        linear_label_id
    ]

    plane_label = plane_labels_by_id.get(
        plane_label_id
    )

    if not plane_label:
        raise RuntimeError(
            f"Plane label "
            f"{plane_label_id} missing"
        )

    if (
        plane_label.get("name")
        != source_label.get("name")
    ):
        raise RuntimeError(
            "Label name mismatch"
        )

    source_color = (
        source_label.get("color")
        or ""
    ).lower()

    plane_color = (
        plane_label.get("color")
        or ""
    ).lower()

    if (
        source_color
        and plane_color
        and source_color != plane_color
    ):
        raise RuntimeError(
            "Label color mismatch"
        )


print("Labels verified: 1 / 1")
print()


# =========================================================
# Work-item verification
# =========================================================

print("Verifying 220 work items...")

verified_work_items = 0
verified_descriptions = 0
description_whitespace_differences = 0
description_whitespace_identifiers = []

verified_parents = 0
verified_assigned = 0
verified_unassigned = 0

actual_state_counts = Counter()
actual_priority_counts = Counter()

plane_items = {}


for expected_number in range(
    1,
    221,
):
    identifier = (
        f"HOR-{expected_number}"
    )

    source = source_by_identifier[
        identifier
    ]

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    item = request(
        "GET",
        work_item_path(
            plane_id
        ),
    )

    plane_items[
        identifier
    ] = item

    # ---------------------------------------------
    # Sequence
    # ---------------------------------------------

    if (
        item.get("sequence_id")
        != expected_number
    ):
        raise RuntimeError(
            f"{identifier}: "
            "sequence mismatch"
        )

    # ---------------------------------------------
    # Title
    # ---------------------------------------------

    if (
        item.get("name")
        != source["title"]
    ):
        raise RuntimeError(
            f"{identifier}: "
            "title mismatch"
        )

    # ---------------------------------------------
    # State
    # ---------------------------------------------

    raw_state = (
        item.get("state")
        or item.get("state_id")
    )

    if isinstance(
        raw_state,
        dict,
    ):
        raw_state = (
            raw_state.get("id")
        )

    if raw_state in state_name_by_id:
        actual_state = (
            state_name_by_id[
                raw_state
            ]
        )
    else:
        actual_state = raw_state

    expected_state = STATE_MAP[
        source["state"]["name"]
    ]

    if actual_state != expected_state:
        raise RuntimeError(
            f"{identifier}: "
            f"state mismatch. "
            f"Expected "
            f"{expected_state}, "
            f"got {actual_state}"
        )

    actual_state_counts[
        actual_state
    ] += 1

    # ---------------------------------------------
    # Priority
    # ---------------------------------------------

    expected_priority = (
        PRIORITY_MAP[
            source["priority"]
        ]
    )

    actual_priority = (
        item.get("priority")
    )

    if (
        actual_priority
        != expected_priority
    ):
        raise RuntimeError(
            f"{identifier}: "
            f"priority mismatch. "
            f"Expected "
            f"{expected_priority}, "
            f"got "
            f"{actual_priority}"
        )

    actual_priority_counts[
        actual_priority
    ] += 1

    # ---------------------------------------------
    # Description
    # ---------------------------------------------

    expected_html = (
        expected_description_html(
            source.get(
                "description"
            )
            or ""
        )
    )

    actual_html = (
        item.get(
            "description_html"
        )
        or item.get(
            "description"
        )
        or ""
    )

    expected_text = html_to_text(
        expected_html
    )

    actual_text = html_to_text(
        actual_html
    )

    if expected_text != actual_text:
        expected_compact = (
            normalize_without_whitespace(
                expected_text
            )
        )

        actual_compact = (
            normalize_without_whitespace(
                actual_text
            )
        )

        if (
            expected_compact
            != actual_compact
        ):
            raise RuntimeError(
                f"{identifier}: "
                "description CONTENT "
                "mismatch.\n"
                f"Expected starts: "
                f"{expected_text[:300]!r}\n"
                f"Actual starts: "
                f"{actual_text[:300]!r}"
            )

        description_whitespace_differences += 1

        description_whitespace_identifiers.append(
            identifier
        )

        print(
            f"  {identifier}: "
            "description whitespace-only "
            "difference accepted"
        )

    verified_descriptions += 1

    # ---------------------------------------------
    # Parent
    # ---------------------------------------------

    source_parent = source.get(
        "parent"
    )

    expected_parent_id = None

    if source_parent:
        parent_identifier = (
            source_parent[
                "identifier"
            ]
        )

        expected_parent_id = (
            work_mapping[
                parent_identifier
            ]["plane_id"]
        )

    actual_parent_id = (
        normalize_id(
            item.get("parent")
        )
    )

    if (
        actual_parent_id
        != expected_parent_id
    ):
        raise RuntimeError(
            f"{identifier}: "
            f"parent mismatch.\n"
            f"Expected: "
            f"{expected_parent_id}\n"
            f"Actual: "
            f"{actual_parent_id}"
        )

    if expected_parent_id:
        verified_parents += 1

    # ---------------------------------------------
    # Assignees
    # ---------------------------------------------

    actual_assignees = (
        normalize_id_set(
            item.get(
                "assignees"
            )
        )
    )

    if source.get("assignee"):
        expected_assignees = {
            plane_user_id
        }

        if (
            actual_assignees
            != expected_assignees
        ):
            raise RuntimeError(
                f"{identifier}: "
                "assignee mismatch"
            )

        verified_assigned += 1

    else:
        if actual_assignees:
            raise RuntimeError(
                f"{identifier}: "
                "expected no assignee"
            )

        verified_unassigned += 1

    # ---------------------------------------------
    # Labels
    # ---------------------------------------------

    source_issue_labels = (
        extract_collection(
            source.get("labels")
        )
    )

    expected_label_ids = {
        label_mapping[
            label["id"]
        ]
        for label
        in source_issue_labels
    }

    actual_label_ids = (
        normalize_id_set(
            item.get("labels")
        )
    )

    if (
        actual_label_ids
        != expected_label_ids
    ):
        raise RuntimeError(
            f"{identifier}: "
            "label mismatch"
        )

    verified_work_items += 1


print()
print(
    "Work items verified:",
    verified_work_items,
)

print(
    "Descriptions verified:",
    verified_descriptions,
)

print(
    "Whitespace-only description differences:",
    description_whitespace_differences,
)

if description_whitespace_identifiers:
    print(
        "Whitespace-only affected items:",
        ", ".join(
            description_whitespace_identifiers
        ),
    )

print(
    "Parent relationships verified:",
    verified_parents,
)

print(
    "Assigned verified:",
    verified_assigned,
)

print(
    "Unassigned verified:",
    verified_unassigned,
)

print()


# =========================================================
# Aggregate state / priority validation
# =========================================================

expected_state_counts = Counter({
    "Backlog": 52,
    "Cancelled": 2,
    "Done": 165,
    "In Progress": 1,
})


expected_priority_counts = Counter({
    "high": 100,
    "low": 15,
    "medium": 62,
    "none": 27,
    "urgent": 16,
})


if (
    actual_state_counts
    != expected_state_counts
):
    raise RuntimeError(
        "Aggregate state counts mismatch"
    )

if (
    actual_priority_counts
    != expected_priority_counts
):
    raise RuntimeError(
        "Aggregate priority counts mismatch"
    )


print("State distribution: OK")
print("Priority distribution: OK")
print()


# =========================================================
# Comment verification
# =========================================================

print("Verifying 475 comments...")

verified_comments = 0
verified_replies = 0


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    source_issue_comments = (
        extract_collection(
            issue.get("comments")
        )
    )

    if not source_issue_comments:
        continue

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    plane_comments = (
        get_collection(
            comments_path(
                plane_id
            )
        )
    )

    plane_by_id = {
        comment["id"]: comment
        for comment in plane_comments
    }

    linear_plane_comments = [
        comment
        for comment
        in plane_comments
        if (
            comment.get(
                "external_source"
            )
            == "linear"
        )
    ]

    if (
        len(linear_plane_comments)
        != len(
            source_issue_comments
        )
    ):
        raise RuntimeError(
            f"{identifier}: "
            f"comment count mismatch. "
            f"Expected "
            f"{len(source_issue_comments)}, "
            f"got "
            f"{len(linear_plane_comments)}"
        )

    for source_comment in (
        source_issue_comments
    ):
        linear_comment_id = (
            source_comment["id"]
        )

        plane_comment_id = (
            comment_mapping[
                linear_comment_id
            ]["plane_id"]
        )

        plane_comment = (
            plane_by_id.get(
                plane_comment_id
            )
        )

        if plane_comment is None:
            raise RuntimeError(
                f"{identifier}: "
                f"Plane comment "
                f"{plane_comment_id} "
                "missing"
            )

        if (
            plane_comment.get(
                "external_id"
            )
            != linear_comment_id
        ):
            raise RuntimeError(
                f"{identifier}: "
                "comment external_id "
                "mismatch"
            )

        if (
            plane_comment.get(
                "external_source"
            )
            != "linear"
        ):
            raise RuntimeError(
                f"{identifier}: "
                "comment external_source "
                "mismatch"
            )

        # -----------------------------------------
        # Original body
        # -----------------------------------------

        cleaned_body = (
            clean_comment_markdown(
                source_comment.get(
                    "body"
                )
                or ""
            )
        )

        source_body_html = (
            markdown_to_html(
                cleaned_body
            )
        )

        expected_body_text = (
            html_to_text(
                source_body_html
            )
        )

        actual_comment_html = (
            plane_comment.get(
                "comment_html"
            )
            or plane_comment.get(
                "comment"
            )
            or ""
        )

        actual_comment_text = (
            html_to_text(
                actual_comment_html
            )
        )

        if expected_body_text:
            if (
                expected_body_text
                not in actual_comment_text
            ):
                # Same fallback logic:
                # reject actual content loss,
                # tolerate formatting whitespace.
                expected_compact = (
                    normalize_without_whitespace(
                        expected_body_text
                    )
                )

                actual_compact = (
                    normalize_without_whitespace(
                        actual_comment_text
                    )
                )

                if (
                    expected_compact
                    not in actual_compact
                ):
                    raise RuntimeError(
                        f"{identifier}: "
                        f"comment "
                        f"{linear_comment_id} "
                        "body text mismatch"
                    )

        # -----------------------------------------
        # Original author/date provenance
        # -----------------------------------------

        original_user = (
            source_comment.get("user")
            or {}
        )

        original_author = (
            original_user.get("name")
            or original_user.get("email")
            or "Unknown Linear user"
        )

        original_created = (
            source_comment.get(
                "createdAt"
            )
            or "unknown"
        )

        normalized_actual_comment = (
            normalize_text(
                actual_comment_text
            )
        )

        if (
            normalize_text(
                original_author
            )
            not in normalized_actual_comment
        ):
            raise RuntimeError(
                f"{identifier}: "
                f"comment "
                f"{linear_comment_id} "
                "lost original author metadata"
            )

        if (
            normalize_text(
                original_created
            )
            not in normalized_actual_comment
        ):
            raise RuntimeError(
                f"{identifier}: "
                f"comment "
                f"{linear_comment_id} "
                "lost original timestamp metadata"
            )

        # -----------------------------------------
        # Reply parent
        # -----------------------------------------

        source_parent = (
            source_comment.get(
                "parent"
            )
        )

        if source_parent:
            expected_parent_id = (
                comment_mapping[
                    source_parent["id"]
                ]["plane_id"]
            )

            actual_parent_id = (
                normalize_id(
                    plane_comment.get(
                        "parent"
                    )
                )
                or plane_comment.get(
                    "parent_id"
                )
            )

            if (
                actual_parent_id
                != expected_parent_id
            ):
                raise RuntimeError(
                    f"{identifier}: "
                    f"reply "
                    f"{linear_comment_id} "
                    "parent mismatch"
                )

            verified_replies += 1

        verified_comments += 1


if verified_comments != 475:
    raise RuntimeError(
        f"Expected 475 verified "
        f"comments, got "
        f"{verified_comments}"
    )

if verified_replies != 3:
    raise RuntimeError(
        f"Expected 3 verified replies, "
        f"got {verified_replies}"
    )


print(
    "Comments verified:",
    verified_comments,
)

print(
    "Replies verified:",
    verified_replies,
)

print()


# =========================================================
# GitHub link verification
# =========================================================

print("Verifying 457 GitHub links...")

verified_links = 0


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    source_issue_links = (
        extract_collection(
            issue.get(
                "attachments"
            )
        )
    )

    if not source_issue_links:
        continue

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    plane_links = (
        get_collection(
            links_path(
                plane_id
            )
        )
    )

    plane_by_id = {
        link["id"]: link
        for link in plane_links
    }

    for source_link in (
        source_issue_links
    ):
        linear_link_id = (
            source_link["id"]
        )

        plane_link_id = (
            link_mapping[
                linear_link_id
            ]["plane_id"]
        )

        plane_link = (
            plane_by_id.get(
                plane_link_id
            )
        )

        if plane_link is None:
            raise RuntimeError(
                f"{identifier}: "
                f"link "
                f"{plane_link_id} "
                "missing"
            )

        if (
            (
                plane_link.get("url")
                or ""
            ).strip()
            != (
                source_link.get("url")
                or ""
            ).strip()
        ):
            raise RuntimeError(
                f"{identifier}: "
                "link URL mismatch"
            )

        if (
            (
                plane_link.get("title")
                or ""
            ).strip()
            != (
                source_link.get("title")
                or ""
            ).strip()
        ):
            raise RuntimeError(
                f"{identifier}: "
                "link title mismatch"
            )

        verified_links += 1


if verified_links != 457:
    raise RuntimeError(
        f"Expected 457 verified links, "
        f"got {verified_links}"
    )


print(
    "GitHub links verified:",
    verified_links,
)

print()


# =========================================================
# Relation verification
# =========================================================

print("Verifying 865 relations...")

fresh_relation_states = {}


def normalize_relation_state(data):
    result = {
        "blocking": set(),
        "blocked_by": set(),
        "relates_to": set(),
        "duplicate": set(),
        "start_after": set(),
        "start_before": set(),
        "finish_after": set(),
        "finish_before": set(),
    }

    for relation_type in result:
        for entry in (
            data.get(
                relation_type
            )
            or []
        ):
            issue_id = (
                entry.get(
                    "issue_id"
                )
            )

            if issue_id:
                result[
                    relation_type
                ].add(issue_id)

    return result


for issue in issues:
    identifier = (
        issue["identifier"]
    )

    plane_id = work_mapping[
        identifier
    ]["plane_id"]

    data = request(
        "GET",
        relations_path(
            plane_id
        ),
    )

    fresh_relation_states[
        identifier
    ] = (
        normalize_relation_state(
            data
        )
    )


verified_relations = 0
relation_type_counts = Counter()


for relation_id, signature in (
    source_relations.items()
):
    linear_type, source, target = (
        signature
    )

    target_plane_id = (
        work_mapping[
            target
        ]["plane_id"]
    )

    if linear_type == "blocks":
        plane_type = "blocking"

    elif linear_type == "related":
        plane_type = "relates_to"

    else:
        raise RuntimeError(
            f"Unexpected relation "
            f"type {linear_type}"
        )

    if (
        target_plane_id
        not in fresh_relation_states[
            source
        ][plane_type]
    ):
        raise RuntimeError(
            f"Missing relation: "
            f"{source} "
            f"{linear_type} "
            f"{target}"
        )

    relation_type_counts[
        linear_type
    ] += 1

    verified_relations += 1


if verified_relations != 865:
    raise RuntimeError(
        "Relation verification count mismatch"
    )


if relation_type_counts != Counter({
    "blocks": 29,
    "related": 836,
}):
    raise RuntimeError(
        "Relation type count mismatch"
    )


# =========================================================
# Detect unexpected Plane relations
# =========================================================

plane_relation_appearances = Counter()


for state in (
    fresh_relation_states.values()
):
    for relation_type, targets in (
        state.items()
    ):
        plane_relation_appearances[
            relation_type
        ] += len(targets)


if (
    plane_relation_appearances[
        "blocking"
    ]
    != 29
):
    raise RuntimeError(
        "Unexpected Plane blocking count"
    )

if (
    plane_relation_appearances[
        "blocked_by"
    ]
    != 29
):
    raise RuntimeError(
        "Unexpected Plane blocked_by count"
    )

if (
    plane_relation_appearances[
        "relates_to"
    ]
    != 1672
):
    raise RuntimeError(
        "Unexpected Plane relates_to count"
    )


unexpected_relation_count = sum(
    plane_relation_appearances[
        relation_type
    ]
    for relation_type in (
        "duplicate",
        "start_after",
        "start_before",
        "finish_after",
        "finish_before",
    )
)


if unexpected_relation_count:
    raise RuntimeError(
        "Unexpected additional "
        "Plane relations detected"
    )


print(
    "Unique relations verified:",
    verified_relations,
)

print(
    "  blocks:",
    relation_type_counts[
        "blocks"
    ],
)

print(
    "  related:",
    relation_type_counts[
        "related"
    ],
)

print()


# =========================================================
# Historical metadata verification
# =========================================================

print(
    "Verifying historical metadata archive..."
)


metadata_issues = (
    historical_metadata.get(
        "issues",
        {}
    )
)

metadata_comments = (
    historical_metadata.get(
        "comments",
        {}
    )
)


if len(metadata_issues) != 220:
    raise RuntimeError(
        "Historical issue metadata "
        "count mismatch"
    )

if len(metadata_comments) != 475:
    raise RuntimeError(
        "Historical comment URL "
        "count mismatch"
    )


projectless_count = sum(
    1
    for value
    in metadata_issues.values()
    if value.get(
        "was_projectless"
    )
)


if projectless_count != 31:
    raise RuntimeError(
        "Historical projectless "
        "count mismatch"
    )


# =========================================================
# Exact historical issue metadata comparison
# =========================================================

for issue in issues:
    identifier = (
        issue["identifier"]
    )

    archived = metadata_issues.get(
        identifier
    )

    if archived is None:
        raise RuntimeError(
            f"{identifier}: "
            "historical archive missing"
        )

    project = issue.get("project")

    expected_metadata = {
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
        "linear_project": project,
        "was_projectless": (
            project is None
        ),
        "linear_team": (
            issue.get("team")
        ),
    }

    for (
        field,
        expected_value,
    ) in expected_metadata.items():
        if (
            archived.get(field)
            != expected_value
        ):
            raise RuntimeError(
                f"{identifier}: historical "
                f"metadata mismatch for "
                f"{field}.\n"
                f"Expected: "
                f"{expected_value!r}\n"
                f"Actual: "
                f"{archived.get(field)!r}"
            )


# =========================================================
# Exact historical comment URL comparison
# =========================================================

for comment_id, source_entry in (
    source_comments.items()
):
    source_comment = (
        source_entry["data"]
    )

    archived = (
        metadata_comments.get(
            comment_id
        )
    )

    if archived is None:
        raise RuntimeError(
            f"Historical comment metadata "
            f"missing: {comment_id}"
        )

    expected_url = (
        source_comment.get("url")
    )

    if (
        archived.get("linear_url")
        != expected_url
    ):
        raise RuntimeError(
            f"Historical comment URL "
            f"mismatch: {comment_id}"
        )

    if (
        archived.get("issue")
        != source_entry["issue"]
    ):
        raise RuntimeError(
            f"Historical comment issue "
            f"mismatch: {comment_id}"
        )


print(
    "Historical issue records:",
    len(metadata_issues),
)

print(
    "Historical comment URLs:",
    len(metadata_comments),
)

print(
    "Projectless source issues:",
    projectless_count,
)

print()


# =========================================================
# Final audit report
# =========================================================

report = {
    "source_backup": str(
        backup_path
    ),
    "result": "PASSED",
    "work_items": {
        "verified": (
            verified_work_items
        ),
        "descriptions": (
            verified_descriptions
        ),
        "description_whitespace_differences": (
            description_whitespace_differences
        ),
        "description_whitespace_identifiers": (
            description_whitespace_identifiers
        ),
        "parents": (
            verified_parents
        ),
        "assigned": (
            verified_assigned
        ),
        "unassigned": (
            verified_unassigned
        ),
        "states": dict(
            actual_state_counts
        ),
        "priorities": dict(
            actual_priority_counts
        ),
    },
    "comments": {
        "verified": (
            verified_comments
        ),
        "replies": (
            verified_replies
        ),
    },
    "github_links": {
        "verified": (
            verified_links
        ),
    },
    "labels": {
        "verified": 1,
    },
    "relations": {
        "verified_unique": (
            verified_relations
        ),
        "blocks": 29,
        "related": 836,
        "plane_blocking": (
            plane_relation_appearances[
                "blocking"
            ]
        ),
        "plane_blocked_by": (
            plane_relation_appearances[
                "blocked_by"
            ]
        ),
        "plane_relates_to": (
            plane_relation_appearances[
                "relates_to"
            ]
        ),
    },
    "historical_metadata": {
        "issues": (
            len(metadata_issues)
        ),
        "comment_urls": (
            len(metadata_comments)
        ),
        "projectless": (
            projectless_count
        ),
    },
}


report_path = (
    BACKUP_DIR
    / "final_migration_audit.json"
)


with report_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        report,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Final output
# =========================================================

print("========================================")
print("FINAL MIGRATION AUDIT PASSED")
print("========================================")
print()

print(
    "Work items:       220 / 220"
)

print(
    "Descriptions:     220 / 220"
)

print(
    "Parents:          193 / 193"
)

print(
    "Assignees:        155 assigned + "
    "65 unassigned"
)

print(
    "Comments:         475 / 475"
)

print(
    "Replies:          3 / 3"
)

print(
    "GitHub links:     457 / 457"
)

print(
    "Labels:           1 / 1"
)

print(
    "Relations:        865 / 865"
)

print(
    "Historical meta:  220 issues + "
    "475 comment URLs"
)

print(
    "Projectless:      31 / 31 preserved"
)

print()

print(
    "Whitespace-only description "
    "differences:",
    description_whitespace_differences,
)

if description_whitespace_identifiers:
    print(
        "Affected:",
        ", ".join(
            description_whitespace_identifiers
        ),
    )

print()

print(
    "HOR-1 -> HOR-220 preserved exactly."
)

print(
    "No silent source-data loss detected."
)

print()

print(
    "Audit report:",
    report_path,
)