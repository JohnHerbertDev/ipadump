import requests
import json
from datetime import datetime

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
        return datetime.min

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

    existing_app = find_app(myApps["apps"], bundleID)

    #
