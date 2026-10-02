import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


# =========================================================
# Find latest Linear backup
# =========================================================

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

print("Using backup:", backup_path)
print()


# =========================================================
# Load backup
# =========================================================

with backup_path.open("r", encoding="utf-8") as file:
    backup = json.load(file)

issues = backup["issues"]


# =========================================================
# Helpers
# =========================================================

URL_PATTERN = re.compile(
    r'https?://[^\s<>"\']+'
)


def clean_url(url):
    return url.rstrip(
        ".,);]}!?`"
    )


def domain_of(url):
    try:
        return (
            urlparse(url)
            .netloc
            .lower()
        )
    except Exception:
        return ""


def extract_urls(text):
    if not text:
        return []

    return [
        clean_url(match)
        for match in URL_PATTERN.findall(text)
    ]


def looks_like_asset(url):
    lowered = url.lower()
    domain = domain_of(url)

    asset_markers = (
        "upload",
        "asset",
        "attachment",
        "storage",
        "usercontent",
        "cdn",
    )

    if any(
        marker in domain
        for marker in asset_markers
    ):
        return True

    if any(
        marker in lowered
        for marker in (
            "/uploads/",
            "/assets/",
            "/attachments/",
        )
    ):
        return True

    return False


# =========================================================
# Issue attachment inventory
# =========================================================

attachment_domains = Counter()
attachments_by_domain = defaultdict(list)

attachment_urls = set()


for issue in issues:
    identifier = issue["identifier"]

    attachments = (
        issue.get("attachments", {})
        .get("nodes", [])
    )

    for attachment in attachments:
        url = attachment.get("url")

        if not url:
            continue

        attachment_urls.add(url)

        domain = (
            domain_of(url)
            or "(no domain)"
        )

        attachment_domains[domain] += 1

        attachments_by_domain[domain].append(
            {
                "issue": identifier,
                "title": attachment.get("title"),
                "url": url,
            }
        )


# =========================================================
# URLs embedded in descriptions/comments
# =========================================================

embedded_urls = set()
embedded_occurrences = []

embedded_domains = Counter()


def inspect_text(identifier, source, text):
    for url in extract_urls(text):
        embedded_urls.add(url)

        domain = (
            domain_of(url)
            or "(no domain)"
        )

        embedded_domains[domain] += 1

        embedded_occurrences.append(
            {
                "issue": identifier,
                "source": source,
                "url": url,
                "domain": domain,
                "looks_like_asset": (
                    looks_like_asset(url)
                ),
            }
        )


for issue in issues:
    identifier = issue["identifier"]

    inspect_text(
        identifier,
        "description",
        issue.get("description"),
    )

    for comment in issue.get(
        "comments",
        [],
    ):
        inspect_text(
            identifier,
            "comment",
            comment.get("body"),
        )

    documents = (
        issue.get("documents", {})
        .get("nodes", [])
    )

    for document in documents:
        inspect_text(
            identifier,
            "document",
            document.get("content"),
        )


# =========================================================
# Classify likely Linear-hosted assets
# =========================================================

likely_asset_urls = sorted(
    {
        row["url"]
        for row in embedded_occurrences
        if row["looks_like_asset"]
    }
)

linear_internal_urls = sorted(
    {
        url
        for url in embedded_urls
        if domain_of(url) == "linear.app"
    }
)


# =========================================================
# Save machine-readable inventory
# =========================================================

inventory = {
    "backup": str(backup_path),
    "issue_attachments": {
        "unique_urls": sorted(
            attachment_urls
        ),
        "by_domain": dict(
            attachment_domains
        ),
    },
    "embedded_urls": {
        "unique_urls": sorted(
            embedded_urls
        ),
        "by_domain": dict(
            embedded_domains
        ),
        "linear_internal_urls": (
            linear_internal_urls
        ),
        "likely_asset_urls": (
            likely_asset_urls
        ),
    },
    "embedded_occurrences": (
        embedded_occurrences
    ),
}


inventory_path = (
    backup_dir
    / "linear_asset_inventory.json"
)

with inventory_path.open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        inventory,
        file,
        ensure_ascii=False,
        indent=2,
    )


# =========================================================
# Report
# =========================================================

print("========================================")
print("LINEAR ASSET AUDIT")
print("========================================")

print(
    "Issue attachment rows:",
    sum(attachment_domains.values()),
)

print(
    "Unique attachment URLs:",
    len(attachment_urls),
)

print()

print("Attachment domains:")

for domain, count in attachment_domains.most_common():
    print(
        f"  {domain}: {count}"
    )


print()
print(
    "Unique embedded URLs:",
    len(embedded_urls),
)

print()

print("Embedded URL domains:")

for domain, count in embedded_domains.most_common():
    print(
        f"  {domain}: {count}"
    )


print()
print(
    "Linear internal URLs:",
    len(linear_internal_urls),
)

print(
    "Likely hosted asset URLs:",
    len(likely_asset_urls),
)


if likely_asset_urls:
    print()
    print(
        "Likely asset domains:"
    )

    asset_domains = Counter(
        domain_of(url)
        for url in likely_asset_urls
    )

    for domain, count in (
        asset_domains.most_common()
    ):
        print(
            f"  {domain}: {count}"
        )


print()
print(
    "Inventory:",
    inventory_path,
)

print()
print(
    "No files downloaded."
)

print(
    "Plane remains untouched."
)