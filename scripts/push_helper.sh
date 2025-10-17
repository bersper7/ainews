#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL=${1:-git@github.com:bersper7/ainews.git}

git init
git add -A
git -c user.name="automation" -c user.email="automation@example.com" -c commit.gpgsign=false commit -m "GeekNews→Notion automation: initial"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"
git push -u origin main

echo "Pushed to $REMOTE_URL"
