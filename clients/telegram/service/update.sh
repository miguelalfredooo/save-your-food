#!/bin/bash
# Updates the Save Your Food bot to the latest code from GitHub, but only if
# that code passes every check. The new code is tested in a scratch checkout
# first, so a failing update never touches the files the running bot uses.
# On a pass it fast-forwards this copy and restarts the service.
# config.json, fridge.db and the logs are untracked, so an update never
# touches them.
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(git -C "$SERVICE_DIR" rev-parse --show-toplevel)"
LABEL="com.fridgeloop.bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"
cd "$REPO_DIR"

# The project moved from the fridge-loop repo to save-your-food, which has
# its own history, so a copy still pulling from fridge-loop can't
# fast-forward. Say how to move it rather than fail with a git error.
ORIGIN="$(git remote get-url origin)"
case "$ORIGIN" in
    *fridge-loop*)
        echo "! This copy pulls from $ORIGIN, which is archived." >&2
        echo "  The bot now lives in save-your-food. Point this copy at it once:" >&2
        echo "    git remote set-url origin https://github.com/miguelalfredooo/save-your-food.git" >&2
        echo "    git fetch origin && git reset --hard origin/main" >&2
        echo "  config.json and fridge.db are untracked, so the reset keeps them." >&2
        echo "  Then run update.sh again." >&2
        exit 1
        ;;
esac

# Untracked files (config.json, fridge.db) are fine; edits to tracked files
# would be lost or block the fast-forward, so stop and name them.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "! Files the repo tracks have local changes:" >&2
    git status --short --untracked-files=no >&2
    echo "  Commit, stash or undo them, then run update.sh again." >&2
    exit 1
fi

UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [ -z "$UPSTREAM" ]; then
    echo "! The current branch, $(git branch --show-current), doesn't track a GitHub branch." >&2
    echo "  Switch to main (git checkout main) and run update.sh again." >&2
    exit 1
fi

echo "Fetching $UPSTREAM..."
git fetch --quiet origin
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse "$UPSTREAM")"

if [ "$OLD" = "$NEW" ]; then
    echo "Already up to date at $(git log -1 --format='%h %s')."
    exit 0
fi
if ! git merge-base --is-ancestor "$OLD" "$NEW"; then
    echo "! This copy has commits $UPSTREAM doesn't, so it can't simply move forward." >&2
    echo "  See them with: git log --oneline $UPSTREAM..HEAD" >&2
    exit 1
fi

echo "New on $UPSTREAM:"
git log --oneline "$OLD..$NEW" | sed 's/^/  /'

# Check with the Python the service runs on, so a test pass means the bot
# will start. Fall back to python3 when the service isn't installed.
PYTHON3="$(/usr/bin/plutil -extract ProgramArguments.2 raw "$PLIST" 2>/dev/null || true)"
if [ -z "$PYTHON3" ] || [ ! -x "$PYTHON3" ]; then
    PYTHON3="$(which python3 || true)"
fi
if [ -z "$PYTHON3" ]; then
    echo "! No python3 on PATH to run the checks with." >&2
    exit 1
fi

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/save-your-food-update.XXXXXX")"
cleanup() {
    git -C "$REPO_DIR" worktree remove --force "$SCRATCH" 2>/dev/null || rm -rf "$SCRATCH"
    git -C "$REPO_DIR" worktree prune
}
trap cleanup EXIT

echo
echo "Checking the new code with $PYTHON3 before using it..."
git worktree add --quiet --detach "$SCRATCH" "$NEW"
if ! (cd "$SCRATCH" && PYTHON="$PYTHON3" ./check.sh > "$SCRATCH.log" 2>&1); then
    # The section headers, failing test names and zip or syntax problems.
    # The tests' expected "!" lines are left out: they aren't failures.
    grep -E '^(== |FAIL: |ERROR: |FAILED|differs: |missing from zip: |in zip but not|Rebuild it)|^[^ /][^ ]*\.py:[0-9]+: ' \
        "$SCRATCH.log" >&2 || tail -n 30 "$SCRATCH.log" >&2
    echo >&2
    echo "! The new code failed its checks. Nothing changed: the bot keeps running" >&2
    echo "  $(git log -1 --format='%h %s' "$OLD")." >&2
    echo "  Full output: $SCRATCH.log" >&2
    exit 1
fi
rm -f "$SCRATCH.log"
echo "All checks passed."

git merge --quiet --ff-only "$NEW"
echo "Updated to $(git log -1 --format='%h %s')."

if launchctl print "gui/$UID_NUM/$LABEL" > /dev/null 2>&1; then
    launchctl kickstart -k "gui/$UID_NUM/$LABEL"
    echo "Restarted the service. Run status.sh to check on it."
else
    echo "The service isn't installed, so nothing was restarted."
    echo "Restart bot.py if you run it by hand, or install the service with install.sh."
fi
