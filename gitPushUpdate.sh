#!/bin/bash
set -euo pipefail

USER_ID="8529398670"
EMAIL="banjo.kazooie.2955@gmail.com"
KEY="/Users/morpheous/Dropbox/Misc/SSH2/KEYS/github-8529398670"
REMOTE="git@github-$USER_ID:$USER_ID/MediaTracker.git"
BRANCH="master"

is_int() { [[ "$1" =~ ^[0-9]+$ ]]; }

# --- ssh / identity ---
ssh-add -D || true
ssh-add -k "$KEY"

git config --global --unset user.name  || true
git config --global --unset user.email || true

# --- local repo ---
git init -q
git config user.name  "$USER_ID"
git config user.email "$EMAIL"
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"

# --- highest existing v1.0.N tag on the remote (0 if none / repo empty) ---
LAST=$( { git ls-remote --tags --refs origin 'v1.0.*' || true; } \
        | sed -n 's#.*refs/tags/v1\.0\.\([0-9][0-9]*\)$#\1#p' \
        | sort -n | tail -1 )
LAST=${LAST:-0}

# --- pick tag number + commit message ---
if [ -n "${1:-}" ]; then
    MSG="$1"
    if is_int "$1"; then N="$1"; else N=$((LAST + 1)); fi
else
    N=$((LAST + 1))
    MSG="$N"
fi
TAG="v1.0.$N"

# --- commit everything here, replace remote branch, add new tag ---
git add -A
git commit -q --allow-empty -m "$MSG"
git branch -M "$BRANCH"
git tag -f "$TAG"

git push --force origin "$BRANCH"
git push --force origin "refs/tags/$TAG"

echo "Pushed $BRANCH -> $TAG (previous highest: v1.0.$LAST)"