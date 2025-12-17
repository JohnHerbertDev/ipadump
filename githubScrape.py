import requests
import json

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

for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]

    existing_app = find_app(myApps["apps"], bundleID)

    # Fetch releases (always)
    releases = requests.get(
        f"https://api.github.com/repos/{repo}/releases"
    ).json()

    new_versions = []

    for release in releases:
        version = release["tag_name"].replace("v", "")
        date = release["published_at"]
        changelog = release["body"]

        downloadURL = None
        size = None

        for asset in release["assets"]:
            if asset["browser_download_url"].endswith(".ipa"):
                downloadURL = asset["browser_download_url"]
                size = asset["size"]
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

    # 🔁 APP ALREADY EXISTS → ONLY UPDATE VERSIONS
    if existing_app:
        added = 0
        for v in new_versions:
            if not version_exists(existing_app["versions"], v["version"]):
                existing_app["versions"].append(v)
                added += 1

        if added > 0:
            print(f"Updated {bundleID}: added {added} new version(s)")
        else:
            print(f"No new versions for {bundleID}")

        continue

    # ➕ NEW APP → FULL CREATE
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

# Save output
json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
