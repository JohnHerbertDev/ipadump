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
DEFAULT_MAX_PAGES = 1  # 🔒 hard limit unless overridden

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
    """
    GET with retries + proper GitHub rate-limit handling.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)

            # ✅ GitHub rate limit handling
            if response.status_code == 403:
                reset = response.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - int(time.time()))
                    print(f"⏳ GitHub rate limit hit, sleeping {wait}s")
                    time.sleep(wait + 1)
                    continue

                wait = BACKOFF_BASE ** attempt
                print(f"⏳ 403 retry in {wait}s: {url}")
                time.sleep(wait)
                continue

            if response.status_code == 429:
                wait = BACKOFF_BASE ** attempt
                print(f"⏳ 429 retry in {wait}s: {url}")
                time.sleep(wait)
                continue

            if response.status_code >= 400:
                print(f"⚠️ HTTP {response.status_code} for {url}")
                return None

            return response.json()

        except requests.exceptions.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            print(f"⚠️ Network error, retrying in {wait}s: {e}")
            time.sleep(wait)

    print(f"❌ Failed after {MAX_RETRIES} retries: {url}")
    return None


def fetch_releases(repo, max_pages):
    """
    Fetch releases with a hard page limit.
    """
    releases = []

    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/repos/{repo}/releases?per_page={PER_PAGE}&page={page}"
        batch = buffered_get(url)

        if not isinstance(batch, list) or not batch:
            break

        releases.extend(batch)

        # stop early if fewer than PER_PAGE
        if len(batch) < PER_PAGE:
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

    # 🔒 page limit logic
    max_pages = DEFAULT_MAX_PAGES
    if repo_info.get("checkpage", False):
        max_pages = 10  # effectively unlimited but still capped

    # -------------------------
    # FETCH RELEASES
    # -------------------------
    releases = fetch_releases(repo, max_pages)

    if not releases:
        print(f"⚠️ Failed to fetch releases for {repo}")
        continue

    new_versions = []

    for release in releases:
        if release.get("prerelease", False) and not allow_prerelease:
            continue

        assets = release.get("assets", [])
        selected_asset = None

        if keyword:
            for asset in assets:
                if is_valid_ipa(asset) and (
                    keyword in asset["name"].lower()
                    or keyword in asset["browser_download_url"].lower()
                ):
                    selected_asset = asset
                    break

        if not selected_asset:
            for asset in assets:
                if is_valid_ipa(asset):
                    selected_asset = asset
                    break

        if not selected_asset:
            continue

        new_versions.append({
            "version": release["tag_name"].lstrip("v"),
            "date": release["published_at"],
            "localizedDescription": release.get("body", ""),
            "downloadURL": selected_asset["browser_download_url"],
            "size": selected_asset["size"]
        })

    # -------------------------
    # EXISTING APP
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
        continue

    # -------------------------
    # NEW APP (NO README FETCH)
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
        "localizedDescription": repo_data.get("description", ""),
        "iconURL": repo_info.get("iconURL", ""),
        "versions": new_versions
    }

    myApps["apps"].append(app)
    print(f"Added new app: {bundleID}")

# -------------------------
# FINALIZE
# -------------------------
myApps["apps"].sort(key=latest_release_date, reverse=True)
json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
