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
# Private to this account: config.json holds the bot token and API keys,
# fridge.db everyone's data, and the logs can name foods and errors.
chmod 700 "$LOG_DIR"
chmod 600 "$TELEGRAM_DIR/config.json"
for f in "$TELEGRAM_DIR/fridge.db" "$TELEGRAM_DIR/recipes_cache.md" \
         "$TELEGRAM_DIR"/fridge.db.bak-* "$LOG_OUT" "$LOG_ERR"; do
    if [ -e "$f" ]; then chmod 600 "$f"; fi
done

# Simple, install-time rotation: keep one prior generation rather than let a
# log grow forever. This only runs when install.sh does, so it is not
# continuous rotation. A proper ongoing rotation would be newsyslog, but that
# needs a root-owned config file in /etc/newsyslog.d/ for a per-user
# LaunchAgent's logs, which is more moving parts than this setup wants for a
# single-purpose Mac mini. If the logs ever grow enormous between reinstalls,
# switch to newsyslog; until then, this is the deliberate tradeoff.
MAX_LOG_BYTES=$((5 * 1024 * 1024))
for log in "$LOG_OUT" "$LOG_ERR"; do
    if [ -f "$log" ]; then
        size="$(stat -f%z "$log" 2>/dev/null || echo 0)"
        if [ "$size" -gt "$MAX_LOG_BYTES" ]; then
            echo "Rotating $log ($size bytes)..."
            mv -f "$log" "$log.old"
        fi
    fi
done

# Two copies polling getUpdates at once get HTTP 409 errors and lose
# messages, so a hand-started bot.py has to go before the managed one starts.
# Matched on a trailing "bot.py" preceded by a space or slash, not the full
# absolute path: someone who ran it by hand almost certainly typed
# "python3 bot.py" from inside this directory, which never puts the absolute
# path on the command line at all. bot.py's own lock file (.bot.lock) is the
# second line of defense if this ever misses one.
PIDS="$(pgrep -f '[/ ]bot\.py$' || true)"
if [ -n "$PIDS" ]; then
    echo "Stopping bot.py started by hand (pid $PIDS)..."
    kill $PIDS
    sleep 1
    kill -9 $PIDS 2>/dev/null || true
fi

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
