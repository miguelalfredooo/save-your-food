#!/bin/bash
# Stops and removes the Fridge Loop launchd service. Does not touch
# config.json, fridge.db, or the logs.
set -euo pipefail

LABEL="com.fridgeloop.bot"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
rm -f "$PLIST_DEST"

echo "Uninstalled. Logs are still in ~/Library/Logs/fridge-loop if you want them."
