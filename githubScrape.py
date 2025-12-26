import requests
import json
from datetime import datetime, timezone

GITHUB_API = "https://api.github.com"

# Load existing apps and scraping list
myApps = json.load(open("my-apps.json"))
scraping = json.load(open("scraping.json"))

def find_app(apps, bundleID):
    for app in apps:
        if app["bundleIdentifier"] == bundleID:
            return app
    return None

def version_exists(versions, version, date):
    return any(v["version"] == version and v["date"] == date for v in versions)

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

def fetch_all_releases(repo):
    """Fetch all GitHub releases using pagination"""
    releases = []
    page = 1

    while True:
        r = requests.get(
            f"{GITHUB_API}/repos/{repo}/releases",
            params={"per_page": 100, "page": page},
        )
        data = r.json()

        if not isinstance(data, list) or not data:
            break

        releases.extend(data)
        page += 1

    return releases

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

    releases = fetch_all_releases(repo)

    if not releases:
        print(f"⚠️ No releases found for {repo}")
        continue

    new_versions = []

    for release in releases:
        # 🚫 Skip drafts
        if release.get("draft", False):
            continue

        # 🚫 Skip prereleases unless allowed
        if release.get("prerelease", False) and not allow_prerelease:
            continue

        if not release.get("published_at"):
            continue

        version = release["tag_name"].lstrip("v")
        date = release["published_at"]
        changelog = release.get("body", "")

        selected_asset = None

        # 🔍 Keyword match
        if keyword:
            for asset in release["assets"]:
                if is_valid_ipa(asset) and (
                    keyword in asset["name"].lower()
                    or keyword in asset["browser_download_url"].lower()
                ):
                    selected_asset = asset
                    break

        # 🔁 Fallback
        if not selected_asset:
            for asset in release["assets"]:
                if is_valid_ipa(asset):
                    selected_asset = asset
                    break

        if not selected_asset:
            continue

        new_versions.append({
            "version": version,
            "date": date,
            "localizedDescription": changelog,
            "downloadURL": selected_asset["browser_download_url"],
            "size": selected_asset["size"]
        })

    # 🔁 EXISTING APP
    if existing_app:
        added = 0
        for v in new_versions:
            if not version_exists(existing_app["versions"], v["version"], v["date"]):
                existing_app["versions"].append(v)
                added += 1

        print(
            f"Updated {bundleID}: added {added} new version(s)"
            if added else f"No new versions for {bundleID}"
        )
        continue

    # ➕ NEW APP
    if not new_versions:
        print(f"⚠️ No valid IPA releases for {bundleID}, skipping")
        continue

    data = requests.get(f"{GITHUB_API}/repos/{repo}").json()
    readme = requests.get(
        f"https://raw.githubusercontent.com/{repo}/HEAD/README.md"
    ).text

    app = {
        "name": repo_info["name"],
        "bundleIdentifier": bundleID,
        "developerName": data["owner"]["login"],
        "subtitle": data.get("description"),
        "localizedDescription": readme,
        "iconURL": repo_info.get("iconURL", ""),
        "versions": new_versions
    }

    myApps["apps"].append(app)
    print(f"Added new app: {bundleID}")

# 🔽 Sort newest first
myApps["apps"].sort(key=latest_release_date, reverse=True)

json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
