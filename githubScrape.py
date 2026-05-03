import requests
import json
import time
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# -------------------------
# CONFIG
# -------------------------
MAX_RETRIES = 5
BACKOFF_BASE = 2
REQUEST_TIMEOUT = 20
PER_PAGE = 100
MAX_WORKERS = 6  # Parallel HTTP threads

# Rate limiting: default 2 req/sec = ~120/min, well under GitHub's 5000/hr
_RATE_LIMIT = float(os.getenv("RATE_LIMIT_PER_SECOND", "2"))
_MIN_INTERVAL = 1.0 / _RATE_LIMIT
_last_request_time = 0.0
_rate_lock = Lock()

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
    global _last_request_time

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Throttle: enforce minimum gap between requests across all threads
            with _rate_lock:
                now = time.monotonic()
                gap = _MIN_INTERVAL - (now - _last_request_time)
                if gap > 0:
                    time.sleep(gap)
                _last_request_time = time.monotonic()

            r = session.get(url, timeout=REQUEST_TIMEOUT)

            if r.status_code in (403, 429):
                # Respect Retry-After header if GitHub sends one
                retry_after = int(r.headers.get("Retry-After", BACKOFF_BASE ** attempt))
                print(f"⏳ Rate limited ({r.status_code}), retrying in {retry_after}s: {url}")
                time.sleep(retry_after)
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


def is_valid_ipa(asset):
    name = asset["name"].lower()
    url = asset["browser_download_url"].lower()

    if not url.endswith(".ipa"):
        return False

    blocked = ["visionos", "tvos"]
    return not any(b in name or b in url for b in blocked)


def latest_release_date(app):
    if not app.get("versions"):
        return datetime.min.replace(tzinfo=timezone.utc)
    return max(
        datetime.fromisoformat(v["date"].replace("Z", "+00:00"))
        for v in app["versions"]
    )


def process_repo(repo_info, existing_lookup, existing_version_sets):
    """Process a single repo and return (bundleID, new_versions, repo_data_needed).
    repo_data_needed is True when the app is new and we need a separate API call for metadata."""

    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]
    name = repo_info["name"]

    if not repo_info.get("checkGithub", True):
        print(f"⏭️ Skipping GitHub check for {name}")
        return bundleID, [], False

    allow_prerelease = repo_info.get("allowPrerelease", False)
    keyword = repo_info.get("keyword")
    keyword = keyword.lower() if keyword else None
    full_pages = repo_info.get("checkpage", False)

    releases = fetch_releases(repo, full=full_pages)

    if not releases:
        print(f"⚠️ Failed to fetch releases for {repo}")
        return bundleID, [], False

    existing_versions = existing_version_sets.get(bundleID, set())
    new_versions = []

    for release in releases:
        if release.get("prerelease", False) and not allow_prerelease:
            continue

        # Skip if we already have this version (fast set lookup)
        tag = release["tag_name"].lstrip("v")
        if tag in existing_versions:
            continue

        for asset in release.get("assets", []):
            if not is_valid_ipa(asset):
                continue

            # Cache lowercased strings once per asset
            asset_name_lower = asset["name"].lower()
            asset_url_lower = asset["browser_download_url"].lower()

            if keyword and not (keyword in asset_name_lower or keyword in asset_url_lower):
                continue

            new_versions.append({
                "version": tag,
                "date": release["published_at"],
                "localizedDescription": release.get("body", ""),
                "downloadURL": asset["browser_download_url"],
                "size": asset["size"]
            })
            break  # Only pick the first matching asset per release

    is_new_app = bundleID not in existing_lookup
    return bundleID, new_versions, is_new_app


# -------------------------
# LOAD DATA
# -------------------------
with open("my-apps.json", "r") as f:
    myApps = json.load(f)

with open("scraping.json", "r") as f:
    scraping = json.load(f)

# Build O(1) lookup structures up front — avoids O(n) scans inside the loop
existing_lookup = {app["bundleIdentifier"]: app for app in myApps["apps"]}
existing_version_sets = {
    app["bundleIdentifier"]: {v["version"] for v in app.get("versions", [])}
    for app in myApps["apps"]
}

# -------------------------
# PARALLEL FETCH
# -------------------------
results = {}
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {
        executor.submit(process_repo, repo_info, existing_lookup, existing_version_sets): repo_info
        for repo_info in scraping
    }
    for future in as_completed(futures):
        bundleID, new_versions, is_new_app = future.result()
        results[bundleID] = (new_versions, is_new_app)

# -------------------------
# APPLY RESULTS (single-threaded, safe)
# -------------------------
for repo_info in scraping:
    bundleID = repo_info["bundleID"]
    name = repo_info["name"]
    repo = repo_info["github"]

    if bundleID not in results:
        continue

    new_versions, is_new_app = results[bundleID]

    if not new_versions:
        print(f"No new versions for {bundleID}")
        continue

    if not is_new_app:
        existing_app = existing_lookup[bundleID]
        existing_app["versions"].extend(new_versions)
        print(f"Updated {bundleID}: added {len(new_versions)} new version(s)")

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
        existing_lookup[bundleID] = app
        print(f"Added new app: {bundleID}")

# -------------------------
# FINALIZE & WRITE
# -------------------------
myApps["apps"].sort(key=latest_release_date, reverse=True)

# Write once; both outputs are the same data
output = json.dumps(myApps, indent=4)
for path in ("my-apps.json", "altstore-repo.json"):
    with open(path, "w") as f:
        f.write(output)

print("✅ my-apps.json and altstore-repo.json updated successfully")
