#!/bin/bash
# Shows whether the Save Your Food service is running, its pid and last exit
# code, and the tail of both logs.
set -euo pipefail

LABEL="com.fridgeloop.bot"
LOG_DIR="$HOME/Library/Logs/fridge-loop"
UID_NUM="$(id -u)"

echo "=== launchctl ==="
launchctl print "gui/$UID_NUM/$LABEL" 2>&1 || echo "(not installed, or not loaded)"

echo
echo "=== $LOG_DIR/bot.log (last 20 lines) ==="
tail -n 20 "$LOG_DIR/bot.log" 2>/dev/null || echo "(no log yet)"

echo
echo "=== $LOG_DIR/bot.err.log (last 20 lines) ==="
tail -n 20 "$LOG_DIR/bot.err.log" 2>/dev/null || echo "(no log yet)"
