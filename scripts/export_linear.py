import json
import os
from datetime import datetime, timezone
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

LINEAR_API_KEY = os.getenv("LINEAR_API_KEY")
LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID")

if not LINEAR_API_KEY or not LINEAR_TEAM_ID:
    raise RuntimeError("Missing Linear environment variables")


LINEAR_URL = "https://api.linear.app/graphql"

HEADERS = {
    "Authorization": LINEAR_API_KEY,
    "Content-Type": "application/json",
}


# =========================================================
# GraphQL helper
# =========================================================

def graphql(query, variables=None):
    response = requests.post(
        LINEAR_URL,
        headers=HEADERS,
        json={
            "query": query,
            "variables": variables or {},
        },
        timeout=60,
    )

    # Show the real GraphQL/API error before Python raises.
    if not response.ok:
        print()
        print("Linear API error")
        print("Status:", response.status_code)
        print(response.text)
        print()

        response.raise_for_status()

    payload = response.json()

    # GraphQL can return HTTP 200 and still contain errors.
    if payload.get("errors"):
        print()
        print("Linear GraphQL error")
        print(
            json.dumps(
                payload["errors"],
                indent=2,
                ensure_ascii=False,
            )
        )
        print()

        raise RuntimeError("Linear GraphQL returned errors")

    return payload["data"]


# =========================================================
# 1. Discover every issue belonging to team HOR
# =========================================================

LIST_ISSUES_QUERY = """
query Issues($teamId: ID!, $after: String) {
  issues(
    first: 100
    after: $after
    includeArchived: true
    filter: {
      team: {
        id: { eq: $teamId }
      }
    }
  ) {
    nodes {
      id
      identifier
    }

    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def get_all_issue_refs():
    issues = []
    after = None

    while True:
        data = graphql(
            LIST_ISSUES_QUERY,
            {
                "teamId": LINEAR_TEAM_ID,
                "after": after,
            },
        )

        connection = data["issues"]

        issues.extend(connection["nodes"])

        if not connection["pageInfo"]["hasNextPage"]:
            break

        after = connection["pageInfo"]["endCursor"]

    return issues


# =========================================================
# 2. Full issue data
# =========================================================

ISSUE_QUERY = """
query IssueBackup($id: String!) {
  issue(id: $id) {
    id
    identifier
    number
    title
    description
    url
    branchName

    priority
    priorityLabel
    estimate

    createdAt
    updatedAt
    archivedAt
    startedAt
    completedAt
    canceledAt
    dueDate

    state {
      id
      name
      type
      color
      position
    }

    creator {
      id
      name
      email
    }

    assignee {
      id
      name
      email
    }

    team {
      id
      name
      key
    }

    project {
      id
      name
    }

    parent {
      id
      identifier
      title
    }

    children(first: 250) {
      nodes {
        id
        identifier
        title
      }
    }

    labels(first: 250) {
      nodes {
        id
        name
        color
      }
    }

    attachments(first: 250) {
      nodes {
        id
        title
        subtitle
        url
      }
    }

    documents(first: 250) {
      nodes {
        id
        title
        content
        url
        createdAt
        updatedAt
        archivedAt
      }
    }

    relations(first: 250) {
      nodes {
        id
        type

        issue {
          id
          identifier
        }

        relatedIssue {
          id
          identifier
        }
      }
    }

    inverseRelations(first: 250) {
      nodes {
        id
        type

        issue {
          id
          identifier
        }

        relatedIssue {
          id
          identifier
        }
      }
    }
  }
}
"""


# =========================================================
# 3. Comments
# =========================================================
#
# IMPORTANT:
# Linear's Comment GraphQL type does NOT expose an
# "attachments" field. Images/files embedded in comments
# remain referenced inside the Markdown body and we will
# inventory/download those separately later.
# =========================================================

COMMENTS_QUERY = """
query IssueComments($id: String!, $after: String) {
  issue(id: $id) {
    comments(
      first: 100
      after: $after
    ) {
      nodes {
        id
        body
        url

        createdAt
        updatedAt
        archivedAt
        resolvedAt
        quotedText

        parent {
          id
        }

        user {
          id
          name
          email
        }
      }

      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def get_comments(issue_id):
    comments = []
    after = None

    while True:
        data = graphql(
            COMMENTS_QUERY,
            {
                "id": issue_id,
                "after": after,
            },
        )

        connection = data["issue"]["comments"]

        comments.extend(connection["nodes"])

        if not connection["pageInfo"]["hasNextPage"]:
            break

        after = connection["pageInfo"]["endCursor"]

    return comments


# =========================================================
# Helpers
# =========================================================

def issue_number(issue):
    return int(issue["identifier"].split("-")[1])


# =========================================================
# 4. Discover and validate HOR-1 → HOR-220
# =========================================================

refs = get_all_issue_refs()
refs.sort(key=issue_number)

print(f"Issues discovered: {len(refs)}")


numbers = [issue_number(issue) for issue in refs]

expected_numbers = list(range(1, 221))


if numbers != expected_numbers:
    missing = sorted(
        set(expected_numbers) - set(numbers)
    )

    unexpected = sorted(
        set(numbers) - set(expected_numbers)
    )

    raise RuntimeError(
        "HOR sequence is not complete. "
        f"Missing={missing}, "
        f"unexpected={unexpected}"
    )


print("HOR sequence validated: HOR-1 -> HOR-220")
print()


# =========================================================
# 5. Export every issue
# =========================================================

issues = []


for index, ref in enumerate(refs, start=1):
    identifier = ref["identifier"]

    print(
        f"[{index:03}/220] "
        f"Exporting {identifier}..."
    )

    detail = graphql(
        ISSUE_QUERY,
        {
            "id": ref["id"],
        },
    )["issue"]

    detail["comments"] = get_comments(
        ref["id"]
    )

    issues.append(detail)


# =========================================================
# 6. Calculate backup statistics
# =========================================================

unique_relations = set()

comment_count = 0
issue_attachment_count = 0
document_count = 0
projectless_count = 0

parent_issue_count = 0
child_relationship_count = 0


for issue in issues:
    comments = issue.get("comments") or []

    comment_count += len(comments)

    attachments = (
        issue.get("attachments", {})
        .get("nodes", [])
    )

    issue_attachment_count += len(
        attachments
    )

    documents = (
        issue.get("documents", {})
        .get("nodes", [])
    )

    document_count += len(
        documents
    )

    if issue.get("project") is None:
        projectless_count += 1

    if issue.get("parent") is not None:
        parent_issue_count += 1

    children = (
        issue.get("children", {})
        .get("nodes", [])
    )

    child_relationship_count += len(
        children
    )

    relations = (
        issue.get("relations", {})
        .get("nodes", [])
    )

    inverse_relations = (
        issue.get(
            "inverseRelations",
            {},
        )
        .get("nodes", [])
    )

    for relation in relations:
        relation_id = relation.get("id")

        if relation_id:
            unique_relations.add(
                relation_id
            )

    for relation in inverse_relations:
        relation_id = relation.get("id")

        if relation_id:
            unique_relations.add(
                relation_id
            )


# =========================================================
# 7. Build backup object
# =========================================================

backup = {
    "metadata": {
        "source": "Linear",
        "team_id": LINEAR_TEAM_ID,
        "exported_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "issue_count": len(issues),
        "first_identifier": (
            issues[0]["identifier"]
            if issues
            else None
        ),
        "last_identifier": (
            issues[-1]["identifier"]
            if issues
            else None
        ),
    },
    "issues": issues,
}


# =========================================================
# 8. Save backup
# =========================================================

backup_dir = BACKUP_DIR

backup_dir.mkdir(
    parents=True,
    exist_ok=True,
)


timestamp = datetime.now(
    timezone.utc
).strftime(
    "%Y%m%dT%H%M%SZ"
)


backup_path = (
    backup_dir
    / f"linear_backup_{timestamp}.json"
)


with backup_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        backup,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# 9. Final verification summary
# =========================================================

print()
print("========================================")
print("LINEAR BACKUP COMPLETE")
print("========================================")

print(
    "Issues:",
    len(issues),
)

print(
    "Comments:",
    comment_count,
)

print(
    "Issue attachments:",
    issue_attachment_count,
)

print(
    "Documents:",
    document_count,
)

print(
    "Unique relations:",
    len(unique_relations),
)

print(
    "Issues with parent:",
    parent_issue_count,
)

print(
    "Child relationships:",
    child_relationship_count,
)

print(
    "Issues without Linear project:",
    projectless_count,
)

print(
    "First:",
    issues[0]["identifier"],
)

print(
    "Last:",
    issues[-1]["identifier"],
)

print()

print(
    "Backup:",
    backup_path,
)

print()
print(
    "No data has been written to Plane."
)