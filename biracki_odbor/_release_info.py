"""Release-channel metadata.

Edit `GITHUB_REPO` once after you create the private GitHub repo.
Format: 'owner/repo' — e.g. 'owner/repo'. The in-app
updater calls
   https://api.github.com/repos/<GITHUB_REPO>/releases/latest
to find newer versions.

Set `GITHUB_REPO = ""` to disable the update check entirely.
"""

from __future__ import annotations

# GitHub repo for release feed lookups. Set to "" to disable the updater.
GITHUB_REPO: str = "I-SOFT-Mionica/biracki-odbor"

# Optional override URL — leave None to use the GitHub API.
UPDATE_FEED_URL: str | None = None
