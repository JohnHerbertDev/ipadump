import requests
import json

# Load JSON files
myApps = json.load(open("my-apps.json"))      # ← this is a LIST
scraping = json.load(open("scraping.json"))

def find_app(apps, bundleID):
    """Return the app dict if it exists, otherwise None."""
    for app in apps:
        if app.get("bundleIdentifier") == bundleID:
            return app
    return None

def version_exists(versions, version):
    return any(v.get("version") == version for v in versions)

for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]

    # ✅ FIX: pass the LIST directly
    existing_app = find_app(myApps, bundleID)

    # Fetch releases
    releases = requests.get(
        f"https://api.github.com/repos/{repo}/releases"
    ).json()

    new_versions = []

    for release in releases:
        version = release.get("tag_name", "").replace("v", "")
        date = release.get("published_at")
        changelog = release.get("body")

        downloadURL = None
        size = None

        for asset in release.get("assets", []):
            if asset.get("browser_download_url", "").endswith(".ipa"):
                downloadURL = asset["browser_download_url"]
                size = asset.get("size")
                break

        if not downloadURL:
            continue

        new_versions.append({
            "version": version,
            "date": date,
            "localizedDescription": changelog,
            "downloadURL": downloadURL,
            "size": size
        })

    # 🔁 EXISTING APP → ONLY UPDATE VERSIONS
    if existing_app:
        added = 0

        existing_versions = existing_app.get("versions", [])

        for v in new_versions:
            if not version_exists(existing_versions, v["version"]):
                existing_versions.append(v)
                added += 1

        existing_app["versions"] = existing_versions

        if added > 0:
            print(f"Updated {bundleID}: added {added} new version(s)")
        else:
            print(f"No new versions for {bundleID}")

        continue

    # ➕ NEW APP → CREATE FULL ENTRY
    data = requests.get(f"https://api.github.com/repos/{repo}").json()
    readme = requests.get(
        f"https://raw.githubusercontent.com/{repo}/refs/heads/main/README.md"
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

    myApps.append(app)
    print(f"Added new app: {bundleID}")

# Save output
json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
