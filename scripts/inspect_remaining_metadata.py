import json
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BACKUP_DIR = ROOT_DIR / "backups"

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


def user_key(user):
    if not user:
        return None

    return (
        user.get("id"),
        user.get("name"),
        user.get("email"),
    )


creators = Counter()
assignees = Counter()

branch_names = []
linear_urls = []

projected = 0
projectless = 0

created_count = 0
updated_count = 0
started_count = 0
completed_count = 0
canceled_count = 0


for issue in issues:
    creator = user_key(
        issue.get("creator")
    )

    if creator:
        creators[creator] += 1

    assignee = user_key(
        issue.get("assignee")
    )

    if assignee:
        assignees[assignee] += 1

    branch = issue.get("branchName")

    if branch:
        branch_names.append(branch)

    url = issue.get("url")

    if url:
        linear_urls.append(url)

    if issue.get("project"):
        projected += 1
    else:
        projectless += 1

    if issue.get("createdAt"):
        created_count += 1

    if issue.get("updatedAt"):
        updated_count += 1

    if issue.get("startedAt"):
        started_count += 1

    if issue.get("completedAt"):
        completed_count += 1

    if issue.get("canceledAt"):
        canceled_count += 1


print("========================================")
print("REMAINING LINEAR METADATA")
print("========================================")
print()

print("Distinct creators:", len(creators))

for creator, count in creators.items():
    user_id, name, email = creator

    print(
        f"  {count:>3} | "
        f"{name} | "
        f"{email} | "
        f"{user_id}"
    )


print()
print("Distinct assignees:", len(assignees))

for assignee, count in assignees.items():
    user_id, name, email = assignee

    print(
        f"  {count:>3} | "
        f"{name} | "
        f"{email} | "
        f"{user_id}"
    )


print()
print("Project membership:")

print(
    "  In Linear project:",
    projected,
)

print(
    "  Team-only / projectless:",
    projectless,
)


print()
print("Historical timestamps:")

print(
    "  createdAt:",
    created_count,
)

print(
    "  updatedAt:",
    updated_count,
)

print(
    "  startedAt:",
    started_count,
)

print(
    "  completedAt:",
    completed_count,
)

print(
    "  canceledAt:",
    canceled_count,
)


print()
print("Branch names:")

print(
    "  Total:",
    len(branch_names),
)

print(
    "  Unique:",
    len(set(branch_names)),
)


print()
print("Original Linear issue URLs:")

print(
    "  Total:",
    len(linear_urls),
)

print(
    "  Unique:",
    len(set(linear_urls)),
)


print()
print("========================================")
print("INSPECTION COMPLETE")
print("========================================")
print()

print(
    "No data was modified in Linear or Plane."
)