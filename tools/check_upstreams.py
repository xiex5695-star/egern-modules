#!/usr/bin/env python3
"""Read-only upstream version checker for reviewed GitHub source files.

Each manifest entry: {"name":"Amap","repo":"owner/repo",
"path":"path/to/file","ref":"main","reviewed_sha":"40-character commit SHA"}
No upstream source is downloaded or executed. An unconfigured manifest is OK.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "upstreams.json").read_text(encoding="utf-8"))
if not isinstance(data, list):
    raise SystemExit("upstreams.json must be an array")
token = os.environ.get("GH_TOKEN", "")
headers = {"Accept": "application/vnd.github+json", "User-Agent": "egern-modules-upstream-watch"}
if token:
    headers["Authorization"] = "Bearer " + token
issues = []
errors = []
for item in data:
    name = item.get("name", "")
    repo = item.get("repo", "")
    path = item.get("path", "")
    ref = item.get("ref", "main")
    pinned = item.get("reviewed_sha", "")
    if not (name and re.fullmatch(r"[\w.-]+/[\w.-]+", repo)
            and path and not path.startswith("/") and ".." not in path.split("/")
            and re.fullmatch(r"[\w./-]+", ref)
            and re.fullmatch(r"[0-9a-fA-F]{40}", pinned)):
        errors.append("Invalid manifest entry: " + str(name))
        continue
    query = urllib.parse.urlencode({"path": path, "sha": ref, "per_page": "1"})
    url = "https://api.github.com/repos/" + repo + "/commits?" + query
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as response:
            commits = json.load(response)
        if not commits:
            errors.append("No commits found for " + name)
            continue
        current = commits[0]["sha"]
        print(name + ": " + current[:12] + (" (unchanged)" if current == pinned else " (changed)"))
        if current != pinned:
            issues.append((name, repo, path, pinned, current))
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
        errors.append("Could not check " + name + ": " + str(exc)[:160])

for name, repo, path, pinned, current in issues:
    title = "Upstream update: " + name
    body = ("An upstream version changed. Review before updating production modules.\n\n"
            + "Source: https://github.com/" + repo + "/blob/" + current + "/" + path + "\n"
            + "Reviewed commit: " + pinned + "\n"
            + "Latest commit affecting file: " + current + "\n\n"
            + "Check license, changed code, permissions, Egern compatibility and device behavior. "
            + "Do not auto-merge.")
    if not token or not os.environ.get("GITHUB_REPOSITORY"):
        print(title + "\n" + body)
        continue
    try:
        found = subprocess.run(["gh", "issue", "list", "--repo", os.environ["GITHUB_REPOSITORY"],
            "--state", "open", "--search", title + " in:title", "--json", "title",
            "--limit", "100"], check=True, capture_output=True, text=True)
        if any(i.get("title") == title for i in json.loads(found.stdout)):
            print("Already has open issue: " + title)
            continue
        subprocess.run(["gh", "issue", "create", "--repo", os.environ["GITHUB_REPOSITORY"],
            "--title", title, "--body", body], check=True)
    except (subprocess.CalledProcessError, ValueError) as exc:
        errors.append("Could not create issue for " + name + ": " + str(exc))
for err in errors:
    print("WARNING: " + err, file=sys.stderr)
if errors:
    sys.exit(1)
