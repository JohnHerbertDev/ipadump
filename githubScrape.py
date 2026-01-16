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
CACHE_FILE = "release-cache.json"

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
# LOAD CACHE
# -------------------------
if os.path.exists(CACHE_FILE):
    release_cache = json.load(open(CACHE_FILE))
else:
    release_cache = {}

# -------------------------
# HELPERS
# -------------------------
def buffered_get(url, raw=False):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)

            if response.status_code in (403, 429):
                wait = BACKOFF_BASE ** attempt
                print(f"⏳ Rate limited ({response.status_code}), retrying in {wait}s: {url}")
                time.sleep(wait)
                continue

            if response.status_code >= 400:
                print(f"⚠️ HTTP {response.status_code} for {url}")
                return None

            return response.text if raw else response.json()

        except requests.exceptions.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            print(f"⚠️ Network error, retrying in {wait}s: {e}")
            time.sleep(wait)

    print(f"❌ Failed after {MAX_RETRIES} retries: {url}")
    return None


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
myApps = json.load(open("my-apps.json"))
scraping = json.load(open("scraping.json"))

# -------------------------
# MAIN LOOP
# -------------------------
for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]
    keyword = repo_info.get("keyword")
    allow_prerelease = repo_info.get("allowPrerelease", False)

    if not repo_info.get("checkGithub", True):
        print(f"⏭️ Skipping GitHub check for {repo_info['name']}")
        continue

    keyword = keyword.lower() if keyword else None
    existing_app = find_app(myApps["apps"], bundleID)

    cached_tag = release_cache.get(repo)
    new_versions = []
    page = 1
    stop_scanning = False

    # -------------------------
    # FETCH RELEASES (PAGE 1 ONLY by default)
    # -------------------------
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page={PER_PAGE}&page={page}"
        releases = buffered_get(url)

        if not isinstance(releases, list) or not releases:
            break

        for release in releases:
            tag = release["tag_name"].lstrip("v")

            # 🔥 CACHE HIT → STOP EVERYTHING
            if cached_tag == tag:
                stop_scanning = True
                break

            if release.get("prerelease", False) and not allow_prerelease:
                continue

            for asset in release.get("assets", []):
                if not is_valid_ipa(asset):
                    continue

                if keyword and keyword not in asset["name"].lower() and keyword not in asset["browser_download_url"].lower():
                    continue

                new_versions.append({
                    "version": tag,
                    "date": release["published_at"],
                    "localizedDescription": release.get("body", ""),
                    "downloadURL": asset["browser_download_url"],
                    "size": asset["size"]
                })
                break

        if stop_scanning or not repo_info.get("checkpage", False):
            break

        page += 1

    # -------------------------
    # EXISTING APP
    # -------------------------
    if existing_app:
        added = 0
        for v in new_versions:
            if not version_exists(existing_app["versions"], v["version"]):
                existing_app["versions"].append(v)
                added += 1

        if added:
            release_cache[repo] = new_versions[0]["version"]
            print(f"Updated {bundleID}: added {added} new version(s)")
        else:
            print(f"No new versions for {bundleID}")

        continue

    # -------------------------
    # NEW APP
    # -------------------------
    if not new_versions:
        print(f"⚠️ No valid IPA releases for {bundleID}, skipping")
        continue

    repo_data = buffered_get(f"https://api.github.com/repos/{repo}") or {}

    app = {
        "name": repo_info["name"],
        "bundleIdentifier": bundleID,
        "developerName": repo_data.get("owner", {}).get("login", repo.split("/")[0]),
        "subtitle": repo_data.get("description", ""),
        "localizedDescription": "",
        "iconURL": repo_info.get("iconURL", ""),
        "versions": new_versions
    }

    myApps["apps"].append(app)
    release_cache[repo] = new_versions[0]["version"]
    print(f"Added new app: {bundleID}")

# -------------------------
# FINALIZE
# -------------------------
myApps["apps"].sort(key=latest_release_date, reverse=True)

json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
json.dump(release_cache, open(CACHE_FILE, "w"), indent=2)
