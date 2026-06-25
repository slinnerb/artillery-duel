"""Self-update via GitHub Releases.

How it works:
  1. "Check for Updates" hits the GitHub API for the latest release.
  2. If its tag (e.g. v1.0.1) is newer than version.py, we offer to update.
  3. We download the new .exe next to the running one, then use the Windows
     trick of renaming the *running* exe out of the way and dropping the new
     one in its place, relaunch it, and exit.

This only does the swap when running as a packaged .exe (PyInstaller). From
source there is nothing to swap, so it just reports whether a newer release
exists.

>>> Before your first release, set GITHUB_OWNER / GITHUB_REPO below. <<<
"""

import json
import os
import subprocess
import sys
import urllib.request

from version import __version__

# ---- Fill these in with your GitHub repo (must be a PUBLIC repo) ----------
GITHUB_OWNER = "slinnerb"
GITHUB_REPO = "artillery-duel"
# ---------------------------------------------------------------------------

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_HEADERS = {"User-Agent": "ArtilleryDuel-Updater", "Accept": "application/vnd.github+json"}


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def _parse(tag):
    """'v1.2.3' -> (1, 2, 3) so versions compare numerically."""
    parts = []
    for chunk in tag.lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check_for_update(timeout=8):
    """Return {'latest', 'url', 'notes'} if a newer release exists, else None.

    Raises on network/parse errors so the caller can show a message.
    """
    req = urllib.request.Request(API_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)

    tag = data.get("tag_name", "")
    if not tag or _parse(tag) <= _parse(__version__):
        return None

    # Releases also carry the installer (ArtilleryDuel-Setup.exe). The updater
    # only swaps the raw game binary, so grab that one specifically and never
    # the installer.
    assets = data.get("assets", [])
    url = None
    for asset in assets:
        if asset.get("name", "").lower() == "artilleryduel.exe":
            url = asset.get("browser_download_url")
            break
    if not url:  # fallback: any .exe that clearly isn't an installer
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe") and "setup" not in name and "install" not in name:
                url = asset.get("browser_download_url")
                break
    if not url:
        return None
    return {"latest": tag.lstrip("vV"), "url": url, "notes": data.get("body", "")}


def _download(url, dest, progress=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "ArtilleryDuel-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length", 0))
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress and total:
                    progress(got / total)
    if progress:
        progress(1.0)


def apply_update(url, progress=None):
    """Download the new exe, swap it in, relaunch, and exit this process."""
    if not is_frozen():
        raise RuntimeError("Updates can only be applied to the packaged .exe build.")

    exe = sys.executable
    folder = os.path.dirname(exe)
    new_path = os.path.join(folder, "_update_new.exe")
    old_path = os.path.join(folder, "_update_old.exe")

    _download(url, new_path, progress)  # if this fails, the live exe is untouched

    if os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    # Windows lets you RENAME a running .exe (you just can't overwrite it).
    os.replace(exe, old_path)   # move the running exe aside
    os.replace(new_path, exe)   # put the new exe in its place

    subprocess.Popen([exe], close_fds=True)
    os._exit(0)


def cleanup_old():
    """Delete the leftover old exe from a previous update. Call at startup."""
    if not is_frozen():
        return
    old_path = os.path.join(os.path.dirname(sys.executable), "_update_old.exe")
    if os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
