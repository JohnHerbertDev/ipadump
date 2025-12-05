import requests
import json

# Load existing apps and scraping list
myApps = json.load(open("my-apps.json"))
scraping = json.load(open("scraping.json"))

def app_exists(apps, bundleID):
    """Return True if an app with this bundleID already exists."""
    return any(a["bundleIdentifier"] == bundleID for a in apps)

for repo_info in scraping:
    repo = repo_info["github"]
    bundleID = repo_info["bundleID"]

    # 🔥 Skip duplicates
    if app_exists(myApps["apps"], bundleID):
        print(f"Skipping duplicate: {bundleID}")
        continue

    # Fetch repository data
    data = requests.get(f"https://api.github.com/repos/{repo}").json()
    readme = requests.get(
        f"https://raw.githubusercontent.com/{repo}/refs/heads/main/README.md"
    ).text

    name = repo_info["name"]
    author = data["owner"]["login"]
    subtitle = data["description"]
    localizedDescription = readme
    versions = []

    # Fetch releases
    releases = requests.get(
        f"https://api.github.com/repos/{repo}/releases"
    ).json()

    for release in releases:
        version = release["tag_name"].replace("v", "")
        date = release["published_at"]
        changelog = release["body"]

        downloadURL = None
        size = None

        # Find IPA asset
        for asset in release["assets"]:
            if asset["browser_download_url"].endswith(".ipa"):
                downloadURL = asset["browser_download_url"]
                size = asset["size"]
                break

        # Skip releases with no IPA
        if not downloadURL:
            continue

        versions.append({
            "version": version,
            "date": date,
            "localizedDescription": changelog,
            "downloadURL": downloadURL,
            "size": size
        })

    # Use iconURL directly from scraping.json
    iconURL = repo_info.get("iconURL", "")

    # Build app entry
    app = {
        "name": name,
        "bundleIdentifier": bundleID,
        "developerName": author,
        "subtitle": subtitle,
        "localizedDescription": localizedDescription,
        "iconURL": iconURL,
        "versions": versions
    }

    # Append ONLY if not a duplicate
    myApps["apps"].append(app)
    print(f"Added: {bundleID}")

# Write updated repo
json.dump(myApps, open("altstore-repo.json", "w"), indent=4)