import os
from pathlib import Path

import requests
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

load_dotenv(ROOT_DIR / ".env")

LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY")
LINEAR_PROJECT_ID = os.getenv("LINEAR_PROJECT_ID")

if not LINEAR_API_KEY or not LINEAR_TEAM_ID:
    raise RuntimeError("Missing Linear environment variables")


LINEAR_URL = "https://api.linear.app/graphql"

headers = {
    "Authorization": LINEAR_API_KEY,
    "Content-Type": "application/json",
}


def graphql(query, variables=None):
    response = requests.post(
        LINEAR_URL,
        headers=headers,
        json={
            "query": query,
            "variables": variables or {},
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("errors"):
        raise RuntimeError(data["errors"])

    return data["data"]


query = f"""
query MigrationCheck($after: String) {{
  viewer {{
    name
    email
  }}

  issues(
    first: 100
    after: $after
    includeArchived: true
    filter: {{
      team: {{
        id: {{ eq: "{LINEAR_TEAM_ID}" }}
      }}
    }}
  ) {{
    nodes {{
      id
      identifier
      title
    }}

    pageInfo {{
      hasNextPage
      endCursor
    }}
  }}
}}
"""

all_issues = []
after = None
viewer = None

while True:
    data = graphql(
        query,
        {
            "after": after,
        },
    )

    viewer = data["viewer"]

    issues = data["issues"]

    all_issues.extend(issues["nodes"])

    if not issues["pageInfo"]["hasNextPage"]:
        break

    after = issues["pageInfo"]["endCursor"]


def issue_number(issue):
    return int(issue["identifier"].split("-")[1])


all_issues.sort(key=issue_number)

print("Linear API connection successful")
print("User:", viewer["name"])
print("Email:", viewer["email"])
print()
print("Issues found:", len(all_issues))

if all_issues:
    print("First issue:", all_issues[0]["identifier"], "-", all_issues[0]["title"])
    print("Last issue:", all_issues[-1]["identifier"], "-", all_issues[-1]["title"])