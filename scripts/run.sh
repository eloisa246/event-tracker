#!/usr/bin/env bash
#
# Build the calendar and push the result. Designed to be run from cron on your
# own machine or a small VPS.
#
# NOT from GitHub Actions. See docs/COMPLIANCE.md -- using Actions to drive the
# scraping is what got the previous account restricted, in writing, by GitHub
# Support. The compute has to live somewhere that isn't GitHub. GitHub's role
# here is code hosting and publishing the output, which is what it is for.
#
# Usage:  scripts/run.sh [--no-push]
#
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

# One run at a time. A cron that fires while the last run is still rendering
# pages would double the load on every venue we fetch -- which is exactly the
# kind of thing that gets an aggregator blocked.
exec 9>"$REPO/.run.lock"
if ! flock -n 9; then
    echo "another run is in progress; exiting"
    exit 0
fi

# Self-contained venv so cron doesn't depend on whatever python happens to be
# on PATH at 5am.
#
# The completion marker is the point: testing for .venv alone would treat a
# half-finished bootstrap (pip succeeded, browser download failed) as done, and
# every later run would skip repair and fail on the missing browser instead.
# Only a bootstrap that reached the end writes the marker.
# Keyed on the contents of requirements.txt, not just "does .venv exist": a
# pin that changes must actually get installed, and a marker that ignored the
# file would leave cron running last month's dependencies forever.
REQ_HASH="$(md5sum requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.bootstrapped 2>/dev/null || true)" != "$REQ_HASH" ]; then
    echo "bootstrapping .venv"
    python3 -m venv .venv
    ./.venv/bin/pip install --quiet --upgrade pip
    ./.venv/bin/pip install --quiet -r requirements.txt
    # Respect a Chromium that's already installed (PLAYWRIGHT_BROWSERS_PATH, or
    # a previous install) rather than re-downloading ~150MB on every new venv.
    if ! ./.venv/bin/python -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p: p.chromium.executable_path' >/dev/null 2>&1; then
        ./.venv/bin/playwright install --with-deps chromium
    fi
    echo "$REQ_HASH" > .venv/.bootstrapped
fi

./.venv/bin/python scripts/build_calendar.py

if [ "${1:-}" = "--no-push" ]; then
    echo "built; not pushing (--no-push)"
    exit 0
fi

git add data/events.json public/*.ics docs/health.md
if git diff --staged --quiet; then
    echo "no changes"
    exit 0
fi

git commit -q -m "Update calendar ($(date -u '+%Y-%m-%d %H:%M') UTC)"
git push -q origin HEAD
echo "pushed"
