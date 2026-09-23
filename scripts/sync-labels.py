#!/usr/bin/env python3
"""Sync issue labels on the K7S3/candid GitHub repo.

Default behavior is fully offline: prints a create plan for every label in
the taxonomy and touches no network, with no token required.

With --apply, reads GITHUB_TOKEN from the environment and diffs against the
live repo via the GitHub REST API, creating/updating/deleting labels so the
repo matches this file's LABELS set exactly.
"""

import json
import os
import sys
import urllib.request
import urllib.error

OWNER = "K7S3"
REPO = "candid"
API = f"https://api.github.com/repos/{OWNER}/{REPO}/labels"

# name, color (no leading #), description
LABELS = [
    ("type: bug", "d73a4a", "Something isn't working"),
    ("type: enhancement", "a2eeef", "New feature or request"),
    ("type: docs", "0075ca", "Improvements or additions to documentation"),
    ("type: question", "d876e3", "Further information is requested"),
    ("area: jobs", "1d76db", "Job discovery and listings"),
    ("area: match", "5319e7", "Job match scoring"),
    ("area: tailor", "0e8a16", "Tailored resumes and cover letters"),
    ("area: prep", "fbca04", "Interview prep packs and concept deep-dives"),
    ("area: mock", "e99695", "Mock interviews and online judge"),
    ("area: salary", "c2e0c6", "Salary intelligence"),
    ("area: dashboard", "bfd4f2", "Local dashboard"),
    ("area: onboarding", "f9d0c4", "First-run onboarding and data import"),
    ("area: infra", "d4c5f9", "Build, tests, repo tooling, CI"),
    ("priority: p0", "b60205", "Critical: blocks a release"),
    ("priority: p1", "d93f0b", "High: fix soon"),
    ("priority: p2", "fbca04", "Normal: fix when convenient"),
    ("good first issue", "7057ff", "Good for newcomers"),
    ("help wanted", "008672", "Extra attention is needed"),
    ("wontfix", "ffffff", "This will not be worked on"),
    ("duplicate", "cfd3d7", "This issue or pull request already exists"),
]


def plan_offline():
    print(f"Offline create plan for {OWNER}/{REPO} ({len(LABELS)} labels):")
    print()
    for name, color, desc in LABELS:
        print(f"  CREATE  name={name!r}  color=#{color}  description={desc!r}")
    print()
    print("No network used. Re-run with --apply to sync against the live repo.")


def _api(method, url, token, data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "candid-label-sync")
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"GitHub API {method} {url} failed: {exc.status} {detail}", file=sys.stderr)
        sys.exit(1)


def apply():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("ERROR: --apply needs GITHUB_TOKEN in the environment.", file=sys.stderr)
        sys.exit(1)

    # GitHub paginates labels at 100 per page; 20 labels fit in one page.
    _, existing = _api("GET", API + "?per_page=100", token)
    live = {lbl["name"]: lbl for lbl in existing}
    want = {name: (color, desc) for name, color, desc in LABELS}

    created = updated = deleted = 0
    for name, (color, desc) in want.items():
        payload = {"name": name, "color": color, "description": desc}
        if name not in live:
            _api("POST", API, token, payload)
            print(f"created: {name}")
            created += 1
        elif live[name]["color"] != color or live[name].get("description") != desc:
            _api("PATCH", f"{API}/{name}", token, payload)
            print(f"updated: {name}")
            updated += 1

    for name in live:
        if name not in want:
            _api("DELETE", f"{API}/{name}", token)
            print(f"deleted: {name}")
            deleted += 1

    print(f"done: {created} created, {updated} updated, {deleted} deleted.")


def main(argv):
    if len(argv) > 1 and argv[1] == "--apply":
        apply()
    elif len(argv) > 1:
        print(f"Usage: {argv[0]} [--apply]", file=sys.stderr)
        sys.exit(2)
    else:
        plan_offline()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
