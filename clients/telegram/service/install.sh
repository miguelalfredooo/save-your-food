#!/bin/bash
# Installs the Fridge Loop bot as a per-user launchd service, so it starts at
# login and restarts itself if it crashes. Safe to run more than once: it
# boots out any existing copy of the service before installing fresh.
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TELEGRAM_DIR="$(cd "$SERVICE_DIR/.." && pwd)"
LABEL="com.fridgeloop.bot"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/fridge-loop"
LOG_OUT="$LOG_DIR/bot.log"
LOG_ERR="$LOG_DIR/bot.err.log"
UID_NUM="$(id -u)"

PYTHON3="$(which python3 || true)"
if [ -z "$PYTHON3" ]; then
    echo "! No python3 on PATH. Install it, or fix your PATH, then try again." >&2
    exit 1
fi

if [ ! -f "$TELEGRAM_DIR/config.json" ]; then
    echo "! No config.json in $TELEGRAM_DIR." >&2
    echo "  Copy config.example.json to config.json and put your bot token in it first." >&2
    exit 1
fi

echo "Python:  $PYTHON3"
echo "bot.py:  $TELEGRAM_DIR/bot.py"
echo "Logs:    $LOG_DIR"

mkdir -p "$LOG_DIR"

# Idempotent: boot out any existing copy of the service before installing.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true

sed -e "s#__PYTHON3__#$PYTHON3#" \
    -e "s#__BOT_PY__#$TELEGRAM_DIR/bot.py#" \
    -e "s#__WORKDIR__#$TELEGRAM_DIR#" \
    -e "s#__LOG_OUT__#$LOG_OUT#" \
    -e "s#__LOG_ERR__#$LOG_ERR#" \
    "$SERVICE_DIR/$LABEL.plist.template" > "$PLIST_DEST"

launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "Installed and started. Run status.sh to check on it."
