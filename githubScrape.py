import requests
import json
from datetime import datetime, timezone

# Load existing apps and scraping list
myApps = json.load(open("my-apps.json"))
scraping = json.load(open("scraping.json"))

def find_app(apps, bundleID):
    """Return the app dict if it exists, otherwise None."""
    for app in apps:
        if app["bundleIdentifier"] == bundleID:
            return app
    return None

def version_exists(versions, version):
    return any(v["version"] == version for v in versions)

def latest_release_date(app):
    """Return latest release datetime for an app, or epoch if none."""
    if not app.get("versions"):
        # ✅ timezone-aware minimum
        return datetime.min.replace(tzinfo=timezone.utc)

    return max(
        datetime.fromisoformat(v["date"].replace("Z", "+00:00"))
        for v in app["versions"]
    )

def is_valid_ipa(asset):
    """
    Return True if IPA should be included.
    Excludes visionOS and tvOS IPAs (case-insensitive).
    """
    name = asset["name"].lower()
    url = asset["browser_download_url"].lower()

    if not url.endswith(".ipa"):
        return False

    blocked = ["visionos", "tvos"]
    return not any(b in name or b in url for b in blocked)

for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]
    keyword = repo_info.get("keyword")
    keyword = keyword.lower() if keyword else None

    existing_app = find_app(myApps["apps"], bundleID)

    # Fetch releases
    releases = requests.get(
        f"https://api.github.com/repos/{repo}/releases"
    ).json()

    if not isinstance(releases, list):
        print(f"⚠️ Failed to fetch releases for {repo}")
        continue

    new_versions = []

    for release in releases:
        # 🚫 IGNORE PRE-RELEASES
        if release.get("prerelease", False):
            continue

        version = release["tag_name"].replace("v", "")
        date = release["published_at"]
        changelog = release["body"]

        selected_asset = None

        # 🔍 FIRST PASS: keyword match
        if keyword:
            for asset in release["assets"]:
                if not is_valid_ipa(asset):
                    continue

                if keyword in asset["name"].lower() or keyword in asset["browser_download_url"].lower():
                    selected_asset = asset
                    break

        # 🔁 FALLBACK: first valid IPA
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

    # 🔁 EXISTING APP → ONLY ADD NEW VERSIONS
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

    # ➕ NEW APP → FULL CREATE
    if not new_versions:
        print(f"⚠️ No valid IPA releases for {bundleID}, skipping")
        continue

    data = requests.get(f"https://api.github.com/repos/{repo}").json()
    readme = requests.get(
        f"https://raw.githubusercontent.com/{repo}/refs/heads/main/README.md"
    ).text

    app = {
        "name": repo_info["name"],
        "bundleIdentifier": bundleID,
        "developerName": data["owner"]["login"],
        "subtitle": data["description"],
        "localizedDescription": readme,
        "iconURL": repo_info.get("iconURL", ""),
        "versions": new_versions
    }

    myApps["apps"].append(app)
    print(f"Added new app: {bundleID}")

# 🔽 SORT APPS BY LATEST RELEASE DATE (NEWEST FIRST)
myApps["apps"].sort(
    key=latest_release_date,
    reverse=True
)

# Save output
json.dump(myApps, open("altstore-repo.json", "w"), indent=4)