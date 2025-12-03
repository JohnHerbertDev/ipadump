import requests
import json

myApps = json.load(open("my-apps.json"))
scraping = json.load(open("scraping.json"))

for repo_info in scraping:
    repo = repo_info["github"]
    data = requests.get(f"https://api.github.com/repos/{repo}").json()
    readme = requests.get(f"https://raw.githubusercontent.com/{repo}/refs/heads/main/README.md").text

    name = repo_info["name"]
    author = data["owner"]["login"]
    subtitle = data["description"]
    localizedDescription = readme
    versions = []

    releases = requests.get(f"https://api.github.com/repos/{repo}/releases").json()

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

        # If no IPA found, skip this release
        if not downloadURL:
            continue

        versions.append({
            "version": version,
            "date": date,
            "localizedDescription": changelog,
            "downloadURL": downloadURL,
            "size": size
        })

    bundleID = repo_info["bundleID"]

    # 🔥 ICON HANDLING REMOVED — only use the iconURL from scraping.json
    iconURL = repo_info.get("iconURL", "")

    app = {
        "name": name,
        "bundleIdentifier": bundleID,
        "developerName": author,
        "subtitle": subtitle,
        "localizedDescription": localizedDescription,
        "iconURL": iconURL,
        "versions": versions
    }

    myApps["apps"].append(app)

json.dump(myApps, open("altstore-repo.json", "w"), indent=4)
