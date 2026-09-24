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
import onboarding as onb  # noqa: E402

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
    "I stop food going off.\n\n"
    "What did you just buy? Type it, commas between things:\n\n"
    "    milk, spinach, chicken thighs\n\n"
    "Send whatever you like: I sort it. Things with a clock on them get "
    "tracked, and I message you once a day when one needs using. Spices, cans and "
    "rice go to your pantry instead, where I remember them but never nag you."
)

HELP = (
    "Type a list any time. I sort it: perishables get tracked, everything "
    "else goes to your pantry.\n\n"
    "/fridge: what's tracked, soonest first\n"
    "/pantry: what I remember but don't track\n"
    "/nudge: what's at risk right now\n"
    "/undo: take back the last list I added\n"
    "\"those are pantry\": move the last list out of tracking\n"
    "/clear: wipe everything and start over\n"
    "/help: this"
)

CLEAR_ASK = ("This wipes everything: tracked items and pantry both. "
             "There is no getting it back.")


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
        tg.send(chat_id, "You already have things logged \u2014 not seeding over them.")
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


def run_onboarding(tg, con, chat_id, text):
    stage = onb.step(con, chat_id)

    if stage == "1":
        reply, nxt = onb.handle_item(con, chat_id, text)
        tg.send(chat_id, reply)
        if nxt:
            tg.send(chat_id, nxt)
        return

    if stage == "2":
        reply, nxt = onb.handle_list(con, chat_id, text)
        tg.send(chat_id, reply)
        if nxt:
            tg.send(chat_id, nxt, buttons=onb.TIME_BUTTONS)
        return

    # Step 3 is answered with a button and step 4 with a tap on the sample
    # nudge. A typed message at either point is a list, so take it as one.
    onb.set_step(con, chat_id, onb.DONE)
    handle_message(tg, con, {"chat": {"id": chat_id}, "text": text})


def send_sample_nudge(tg, con, chat_id, today=None):
    """Step 4: a real nudge, on a real item of theirs, with live buttons.

    Deliberately not a mock-up. The user needs to see the message that will
    arrive tomorrow, and to find out that one tap ends it, while nothing is at
    stake. If they have nothing perishable yet, say so rather than inventing an
    item — a fake nudge is exactly the thing that costs trust.
    """
    items = fridge.open_items(con, chat_id)
    if not items:
        tg.send(chat_id, "Nothing of yours is on a clock yet, so there is no "
                         "nudge to show you. Send a perishable and you will get "
                         "one tomorrow.")
        return
    soonest = items[0]
    tg.send(chat_id, "%s: %s" % (soonest["name"],
                                    sl.when(soonest["use_by_date"], today)),
            buttons=item_buttons(soonest["id"]))


def handle_message(tg, con, msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        tg.send(chat_id, "I can only read typed lists for now: "
                         "commas between things.")
        return

    # While onboarding is running it owns plain text, because each step is a
    # question and the answer means something different at each one.
    if onb.active(con, chat_id) and not text.startswith("/"):
        run_onboarding(tg, con, chat_id, text)
        return

    low = text.lower()
    if low.startswith("/start"):
        # A first /start onboards. A later one does not restart it: someone
        # tapping /start out of curiosity should not lose their fridge.
        if not onb.started(con, chat_id):
            tg.send(chat_id, onb.begin(con, chat_id))
        else:
            tg.send(chat_id, WELCOME)
        return
    if low.startswith("/setup"):
        tg.send(chat_id, onb.begin(con, chat_id))
        return
    if low.startswith("/skip"):
        tg.send(chat_id, onb.skip(con, chat_id, cfg["nudge_hour"]))
        return
    if low.startswith("/help"):
        tg.send(chat_id, HELP)
        return
    if low.startswith("/fridge"):
        tg.send(chat_id, fridge.compose_inventory(fridge.open_items(con, chat_id)))
        return
    if low.startswith("/pantry"):
        tg.send(chat_id, fridge.compose_pantry(fridge.pantry_items(con, chat_id)))
        return
    if low.startswith("/undo"):
        tg.send(chat_id, fridge.undo_last(con, chat_id))
        return
    if low.startswith("/clear"):
        tg.send(chat_id, CLEAR_ASK, buttons=[[
            {"text": "Yes, wipe it", "callback_data": "clear:yes"},
            {"text": "No, keep it", "callback_data": "clear:no"},
        ]])
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

    # "ok", "thanks", "yes" are answers to me, not things in a fridge. Without
    # this they each become a five-day guess and turn up in tomorrow's nudge.
    if fridge.is_chatter(text):
        tg.send(chat_id, "Noted. Send a list whenever you want to add something, "
                         "or /help for what I can do.")
        return

    # "these items are all from the pantry" is a correction, not an item. Act on
    # it rather than logging the sentence, which is what used to happen.
    fix = fridge.correction(text)
    if fix:
        _, reply = fridge.reclassify_last(con, chat_id, fix)
        tg.send(chat_id, reply)
        return

    # Any other sentence is prose. Logging it produces a dated fridge item with
    # a whole clause for a name, which then turns up in a nudge.
    if fridge.looks_like_sentence(text):
        tg.send(chat_id, "That reads like a sentence rather than a list, so I "
                         "haven't logged it.\n\nFood goes in with commas "
                         "between: milk, spinach, chicken thighs. If I sorted "
                         "your last list wrong, say \"those are pantry\" or "
                         "\"those are fridge\" and I'll move them.")
        return

    names, too_long = fridge.parse_list(text, report=True)

    if too_long:
        tg.send(chat_id, "These were too long to be item names, so I left them "
                         "out rather than guessing: " + "; ".join(too_long))

    if not names:
        tg.send(chat_id, "I couldn't pick any items out of that. "
                         "Try: milk, spinach, chicken thighs")
        return

    tracked, stable, outside, again = fridge.add_items(con, chat_id, names)

    # Lead with what the list actually turned out to be. Someone who sent their
    # spice rack must not read "Logged 0 things" as a failure — the list went
    # somewhere useful, it just was not the tracked pile.
    lines = []
    if tracked:
        lines += ["Tracking %d thing%s:" % (
            len(tracked), "" if len(tracked) == 1 else "s"), ""]
        for name, ub, risk, est in tracked:
            lines.append("  • %s: %s%s" % (
                name, sl.when(ub), " (est.)" if est else ""))
    if again:
        if lines:
            lines.append("")
        lines += ["Already had %s, so I moved the date instead of adding a second one:"
                  % ("this" if len(again) == 1 else "these"),
                  "  " + ", ".join(again)]
    if stable:
        if lines:
            lines.append("")
        lines += ["Put %d in your pantry: no clock on %s, so no nudges:" % (
            len(stable), "it" if len(stable) == 1 else "them"),
            "  " + ", ".join(stable)]
    if outside:
        if lines:
            lines.append("")
        lines += ["These keep better on the counter than in the fridge, so I am "
                  "remembering them without tracking them:",
                  "  " + ", ".join(outside)]
    if stable or outside:
        lines += ["", "/pantry any time to see that list."]
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

    if state == "onb":
        kind, _, val = raw_id.partition(":")
        if kind != "time":
            tg.answer(cb["id"])
            return
        try:
            hour = int(val)
        except ValueError:
            tg.answer(cb["id"])
            return
        fridge.set_pref(con, chat_id, "nudge_hour", hour)
        tg.answer(cb["id"], "%02d:00 it is." % hour)
        tg.edit(chat_id, msg["message_id"], "Your message arrives at %02d:00." % hour)
        onb.set_step(con, chat_id, "4")
        tg.send(chat_id, onb.STEP4_HEAD)
        send_sample_nudge(tg, con, chat_id)
        onb.set_step(con, chat_id, onb.DONE)
        tg.send(chat_id, onb.finished(hour))
        return

    if state == "clear":
        if raw_id != "yes":
            tg.answer(cb["id"], "Left it alone.")
            tg.edit(chat_id, msg["message_id"], "Nothing wiped.")
            return
        n_items, n_pantry = fridge.clear_chat(con, chat_id)
        tg.answer(cb["id"], "Wiped.")
        tg.edit(chat_id, msg["message_id"],
                "Wiped %d tracked item%s and %d pantry entr%s. Send a list when "
                "you are ready." % (n_items, "" if n_items == 1 else "s",
                                    n_pantry, "y" if n_pantry == 1 else "ies"))
        return

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
    target = now.replace(hour=fridge.nudge_hour(con, chat_id, cfg["nudge_hour"]),
                         minute=cfg["nudge_minute"], second=0, microsecond=0)
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
        # Someone halfway through onboarding must not get a scheduled nudge on
        # top of the step they are answering.
        if onb.active(con, chat_id):
            continue
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
