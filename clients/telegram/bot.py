#!/usr/bin/env python3
"""Fridge Loop — Telegram client.

Standard library only. Nothing to install: if you can run python3, you can run this.

  python3 bot.py

Reads config.json for the bot token. The token is never logged or echoed.
"""

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fridge          # noqa: E402
import shelf_life as sl  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "config.json")
API = "https://api.telegram.org/bot%s/%s"

POLL_TIMEOUT = 50      # long-poll seconds
STATE_LABELS = {"used": "Used it", "frozen": "Froze it", "tossed": "Tossed it"}


# --- config ----------------------------------------------------------------

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            "No config.json found.\n"
            "Copy config.example.json to config.json and put your bot token in it.\n"
            "Get a token from @BotFather in Telegram: /newbot"
        )
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    if not cfg.get("token") or "PUT_YOUR" in cfg["token"]:
        sys.exit("config.json has no real token in it yet.")
    cfg.setdefault("nudge_hour", 16)
    cfg.setdefault("nudge_minute", 30)
    return cfg


# --- telegram --------------------------------------------------------------

class Telegram:
    def __init__(self, token):
        self._token = token

    def call(self, method, **params):
        url = API % (self._token, method)
        data = json.dumps(params).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 15) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            print("! telegram %s failed: %s %s" % (method, e.code, body))
        except Exception as e:                     # network blips are expected
            print("! telegram %s failed: %s" % (method, e))
        return None

    def send(self, chat_id, text, buttons=None):
        params = {"chat_id": chat_id, "text": text}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def answer(self, callback_id, text=None):
        self.call("answerCallbackQuery", callback_query_id=callback_id,
                  **({"text": text} if text else {}))

    def edit(self, chat_id, message_id, text):
        self.call("editMessageText", chat_id=chat_id,
                  message_id=message_id, text=text)


# --- conversation ----------------------------------------------------------

WELCOME = (
    "I help you use food before it goes bad.\n\n"
    "Tell me what's in your fridge. Just type it, with commas between things:\n\n"
    "    milk, spinach, chicken thighs\n\n"
    "I'll work out roughly when each one turns. I'll message you once a day when "
    "something needs using. Tap a button to say what happened, and it stops asking."
)

HELP = (
    "Type a list any time to add things.\n\n"
    "/fridge shows what's in there, soonest first\n"
    "/nudge shows what's at risk right now\n"
    "/help shows this"
)


def item_buttons(item_id):
    return [[
        {"text": "✅ Used it", "callback_data": "used:%d" % item_id},
        {"text": "❄️ Froze it", "callback_data": "frozen:%d" % item_id},
        {"text": "\U0001f5d1 Tossed it", "callback_data": "tossed:%d" % item_id},
    ]]


def handle_seed(tg, con, chat_id):
    """Load seed.json into this chat. Refuses if the chat already has anything,
    so a stray /seed can't quietly duplicate a real fridge."""
    path = os.path.join(HERE, "seed.json")
    if not os.path.exists(path):
        tg.send(chat_id, "No seed.json here.")
        return
    if fridge.open_items(con, chat_id):
        tg.send(chat_id, "You already have things logged. I won't seed over them.")
        return
    with open(path) as f:
        data = json.load(f)
    today = date.today().isoformat()
    for it in data.get("items", []):
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
            " VALUES (?,?,?,?,0,?, 'open')",
            (chat_id, it["name"], it["use_by"], it["risk"], today))
    con.commit()
    tg.send(chat_id, "Loaded your current fridge.\n\n"
            + fridge.compose_inventory(fridge.open_items(con, chat_id)))


def send_nudge(tg, con, chat_id, today=None):
    """One message naming what's at risk, then one buttoned line per item.

    The buttons sit on their own short messages on purpose: a single message
    with twelve buttons is unreadable on a phone, and you want to answer for
    one thing at a time.
    """
    today = today or date.today()
    items = fridge.at_risk(con, chat_id, today)
    body = fridge.compose_nudge(items, today)
    if not body:
        return 0
    tg.send(chat_id, body)
    for i in items:
        tg.send(chat_id, "%s: %s" % (i["name"], sl.when(i["use_by_date"], today)),
                buttons=item_buttons(i["id"]))
    return len(items)


def handle_message(tg, con, msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        tg.send(chat_id, "I can only read typed lists for now. "
                         "Put commas between things.")
        return

    low = text.lower()
    if low.startswith("/start"):
        tg.send(chat_id, WELCOME)
        return
    if low.startswith("/help"):
        tg.send(chat_id, HELP)
        return
    if low.startswith("/fridge"):
        tg.send(chat_id, fridge.compose_inventory(fridge.open_items(con, chat_id)))
        return
    if low.startswith("/seed"):
        handle_seed(tg, con, chat_id)
        return
    if low.startswith("/nudge"):
        if send_nudge(tg, con, chat_id) == 0:
            tg.send(chat_id, "Nothing at risk today.")
        return
    if low.startswith("/"):
        tg.send(chat_id, HELP)
        return

    names = fridge.parse_list(text)
    if not names:
        tg.send(chat_id, "I couldn't pick any items out of that. "
                         "Try: milk, spinach, chicken thighs")
        return

    added, outside = fridge.add_items(con, chat_id, names)
    lines = ["Logged %d thing%s:" % (len(added), "" if len(added) == 1 else "s"), ""]
    for name, ub, risk, est in added:
        lines.append("  • %s: %s%s" % (
            name, sl.when(ub), " (est.)" if est else ""))
    if outside:
        lines += ["", "Left these out. They keep better outside the fridge, so I'm "
                      "not tracking them: " + ", ".join(outside)]
    soonest = min((a[1] for a in added), default=None)
    if soonest:
        lines += ["", "First one to watch: %s." % sl.when(soonest)]
    tg.send(chat_id, "\n".join(lines))


def handle_callback(tg, con, cb):
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if ":" not in data or chat_id is None:
        tg.answer(cb["id"])
        return
    state, _, raw_id = data.partition(":")
    if state not in STATE_LABELS:
        tg.answer(cb["id"])
        return
    try:
        item_id = int(raw_id)
    except ValueError:
        tg.answer(cb["id"])
        return

    row = con.execute("SELECT name FROM items WHERE id=? AND chat_id=?",
                      (item_id, chat_id)).fetchone()
    if not row:
        tg.answer(cb["id"], "Already handled.")
        return

    fridge.close_item(con, chat_id, item_id, state)
    tg.answer(cb["id"], STATE_LABELS[state])
    tg.edit(chat_id, msg["message_id"], "%s: %s" % (row["name"], STATE_LABELS[state].lower()))


# --- daily nudge -----------------------------------------------------------

def due_today(con, chat_id, cfg, now):
    """Fire once per day, at or after the configured time. Survives restarts."""
    row = con.execute("SELECT value FROM meta WHERE chat_id=? AND key='last_nudge'",
                      (chat_id,)).fetchone()
    if row and row["value"] == now.date().isoformat():
        return False
    target = now.replace(hour=cfg["nudge_hour"], minute=cfg["nudge_minute"],
                         second=0, microsecond=0)
    return now >= target


def mark_nudged(con, chat_id, day):
    con.execute("INSERT OR REPLACE INTO meta (chat_id,key,value) VALUES (?,'last_nudge',?)",
                (chat_id, day.isoformat()))
    con.commit()


def sweep(tg, con, cfg, now=None):
    """Roll past-budget items into a disposal prompt, then nudge whoever is due."""
    now = now or datetime.now()
    today = now.date()
    chats = [r["chat_id"] for r in
             con.execute("SELECT DISTINCT chat_id FROM items").fetchall()]
    for chat_id in chats:
        if not due_today(con, chat_id, cfg, now):
            continue
        for i in fridge.expired_past_budget(con, chat_id, today):
            tg.send(chat_id,
                    "%s has been past its date for a while now. Safe to assume it's "
                    "gone?" % i["name"],
                    buttons=[[
                        {"text": "\U0001f5d1 Tossed it", "callback_data": "tossed:%d" % i["id"]},
                        {"text": "✅ Used it", "callback_data": "used:%d" % i["id"]},
                    ]])
        send_nudge(tg, con, chat_id, today)
        mark_nudged(con, chat_id, today)


# --- main ------------------------------------------------------------------

def main():
    cfg = load_config()
    tg = Telegram(cfg["token"])
    con = fridge.connect()

    me = tg.call("getMe")
    if not me or not me.get("ok"):
        sys.exit("Couldn't reach Telegram. Check the token and your connection.")
    print("Fridge Loop running as @%s. Nudging at %02d:%02d. Ctrl-C to stop."
          % (me["result"]["username"], cfg["nudge_hour"], cfg["nudge_minute"]))

    offset = None
    while True:
        try:
            res = tg.call("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                          allowed_updates=["message", "callback_query"])
            if res and res.get("ok"):
                for upd in res["result"]:
                    offset = upd["update_id"] + 1
                    if "message" in upd:
                        handle_message(tg, con, upd["message"])
                    elif "callback_query" in upd:
                        handle_callback(tg, con, upd["callback_query"])
            sweep(tg, con, cfg)
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
