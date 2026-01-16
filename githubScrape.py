import requests
import json
import time
import os
from datetime import datetime, timezone

# -------------------------
# CONFIG
# -------------------------
MAX_RETRIES = 5
BACKOFF_BASE = 2
REQUEST_TIMEOUT = 20
PER_PAGE = 100

API_TOKEN = os.getenv("API_TOKEN")

# -------------------------
# SESSION
# -------------------------
session = requests.Session()
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "githubscrape/1.0"
}

if API_TOKEN:
    headers["Authorization"] = f"Bearer {API_TOKEN}"

session.headers.update(headers)

# -------------------------
# HELPERS
# -------------------------
def buffered_get(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)

            if r.status_code in (403, 429):
                wait = BACKOFF_BASE ** attempt
                print(f"⏳ Rate limited ({r.status_code}), retrying in {wait}s: {url}")
                time.sleep(wait)
                continue

            if r.status_code >= 400:
                print(f"⚠️ HTTP {r.status_code} for {url}")
                return None

            return r.json()

        except requests.exceptions.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            print(f"⚠️ Network error, retrying in {wait}s: {e}")
            time.sleep(wait)

    print(f"❌ Failed after {MAX_RETRIES} retries: {url}")
    return None


def fetch_releases(repo, full=False):
    releases = []
    page = 1
    max_pages = None if full else 1

    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page={PER_PAGE}&page={page}"
        batch = buffered_get(url)

        if not isinstance(batch, list) or not batch:
            break

        releases.extend(batch)

        page += 1
        if max_pages and page > max_pages:
            break

    return releases


def find_app(apps, bundleID):
    return next((a for a in apps if a["bundleIdentifier"] == bundleID), None)


def version_exists(versions, version):
    return any(v["version"] == version for v in versions)


def latest_release_date(app):
    if not app.get("versions"):
        return datetime.min.replace(tzinfo=timezone.utc)
    return max(
        datetime.fromisoformat(v["date"].replace("Z", "+00:00"))
        for v in app["versions"]
    )


def is_valid_ipa(asset):
    name = asset["name"].lower()
    url = asset["browser_download_url"].lower()

    if not url.endswith(".ipa"):
        return False

    blocked = ["visionos", "tvos"]
    return not any(b in name or b in url for b in blocked)

# -------------------------
# LOAD DATA
# -------------------------
with open("my-apps.json", "r") as f:
    myApps = json.load(f)

with open("scraping.json", "r") as f:
    scraping = json.load(f)

# -------------------------
# MAIN LOOP
# -------------------------
for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]
    name = repo_info["name"]

    if not repo_info.get("checkGithub", True):
        print(f"⏭️ Skipping GitHub check for {name}")
        continue

    allow_prerelease = repo_info.get("allowPrerelease", False)
    keyword = repo_info.get("keyword")
    keyword = keyword.lower() if keyword else None
    full_pages = repo_info.get("checkpage", False)

    existing_app = find_app(myApps["apps"], bundleID)

    releases = fetch_releases(repo, full=full_pages)

    if not releases:
        print(f"⚠️ Failed to fetch releases for {repo}")
        continue

    new_versions = []

    for release in releases:
        if release.get("prerelease", False) and not allow_prerelease:
            continue

        assets = release.get("assets", [])
        selected = None

        for asset in assets:
            if not is_valid_ipa(asset):
                continue

            if keyword and not (
                keyword in asset["name"].lower()
                or keyword in asset["browser_download_url"].lower()
            ):
                continue

            selected = asset
            break

        if not selected:
            continue

        new_versions.append({
            "version": release["tag_name"].lstrip("v"),
            "date": release["published_at"],
            "localizedDescription": release.get("body", ""),
            "downloadURL": selected["browser_download_url"],
            "size": selected["size"]
        })

    if not new_versions:
        print(f"No new versions for {bundleID}")
        continue

    # -------------------------
    # UPDATE OR CREATE APP
    # -------------------------
    if existing_app:
        added = 0
        for v in new_versions:
            if not version_exists(existing_app["versions"], v["version"]):
                existing_app["versions"].append(v)
                added += 1

        print(
            f"Updated {bundleID}: added {added} new version(s)"
            if added else f"No new versions for {bundleID}"
        )

    else:
        repo_data = buffered_get(f"https://api.github.com/repos/{repo}") or {}

        app = {
            "name": name,
            "bundleIdentifier": bundleID,
            "developerName": repo_data.get("owner", {}).get("login", repo.split("/")[0]),
            "subtitle": repo_data.get("description", ""),
            "localizedDescription": "",
            "iconURL": repo_info.get("iconURL", ""),
            "versions": new_versions
        }

        myApps["apps"].append(app)
        print(f"Added new app: {bundleID}")

# -------------------------
# FINALIZE & WRITE FILES
# -------------------------
myApps["apps"].sort(key=latest_release_date, reverse=True)

# ✅ Persist source of truth
with open("my-apps.json", "w") as f:
    json.dump(myApps, f, indent=4)

# ✅ Generate AltStore repo
with open("altstore-repo.json", "w") as f:
    json.dump(myApps, f, indent=4)

print("✅ my-apps.json and altstore-repo.json updated successfully")
