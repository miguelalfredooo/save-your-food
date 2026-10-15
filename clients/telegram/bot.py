#!/usr/bin/env python3
"""Save Your Food — Telegram client.

Standard library only. Nothing to install: if you can run python3, you can run this.

  python3 bot.py

Reads config.json for the bot token. The token is never logged or echoed.
"""

import base64
import fcntl
import json
import os
import re
import socket
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# Prefer IPv4 for outbound calls. Measured on this project: a getUpdates or
# sendMessage socket that picks an IPv6 route can sit in SYN_SENT for minutes
# before connecting, or time out and silently drop a reply, while IPv4 to the
# same host connects instantly. Falls back to whatever getaddrinfo returned if
# there is no IPv4 route at all, so an IPv6-only network still works.
_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(*args, **kwargs):
    results = _getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 or results


socket.getaddrinfo = _ipv4_first_getaddrinfo

# Everything this process creates (fridge.db, the recipe cache) is readable
# by this account only. The store holds every person's food and the owner's
# recipes, and other accounts on the same Mac have no business reading it.
os.umask(0o077)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fridge          # noqa: E402
import shelf_life as sl  # noqa: E402
import onboarding as onb  # noqa: E402
import card  # noqa: E402
import recipe_text  # noqa: E402
import llm_agent  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "config.json")
LOCK_PATH = os.path.join(HERE, ".bot.lock")
API = "https://api.telegram.org/bot%s/%s"
FILE_API = "https://api.telegram.org/file/bot%s/%s"

POLL_TIMEOUT = 50      # long-poll seconds
REQUEST_DOWNLOAD_TIMEOUT = 30
STATE_LABELS = {"used": "Used it", "frozen": "Froze it", "tossed": "Tossed it"}

MAX_MESSAGE_LENGTH = 2000
MAX_ITEMS_PER_CAPTURE = 50
MAX_CAPTION_LIST_CHARS = 1500
RATE_LIMIT_PER_MINUTE = 20
RATE_LIMIT_WINDOW = 60   # seconds

# In-memory only, not persisted: a burst is a right-now problem, not a
# things-to-remember one, and it resets on restart along with everything else
# process-local. Keyed by chat_id, each value a list of recent message times.
_MSG_TIMES = {}


def _rate_limited(chat_id, now=None):
    """True, and records nothing, once a chat is over budget for this
    window. Under budget, records the hit and returns False."""
    now = now if now is not None else time.time()
    times = _MSG_TIMES.setdefault(chat_id, [])
    cutoff = now - RATE_LIMIT_WINDOW
    while times and times[0] < cutoff:
        times.pop(0)
    if len(times) >= RATE_LIMIT_PER_MINUTE:
        return True
    times.append(now)
    return False


def prune_rate_limits(now=None):
    """Drop chats with no recent messages. Every chat that ever wrote,
    allowed or not, used to keep a key here for the life of the process."""
    cutoff = (now if now is not None else time.time()) - RATE_LIMIT_WINDOW
    for chat_id in [c for c, times in _MSG_TIMES.items()
                    if not times or times[-1] < cutoff]:
        del _MSG_TIMES[chat_id]


def reset_rate_limits():
    """Test hook. The limiter is deliberately process-global state, which a
    test suite reusing the same chat ids across many tests should not
    inherit from an earlier test."""
    _MSG_TIMES.clear()

CLOSE_LINES = {
    "used": "That one did not go to waste.",
    "frozen": "Frozen. Good for months.",
}

# Held back deliberately. A milestone that arrives every Tuesday is not one.
MILESTONES = (10, 25, 50, 100, 250, 500)


def milestone_line(n):
    return "%d things used before they turned. That is the whole idea." % n


# --- config ----------------------------------------------------------------

def acquire_lock():
    """Refuse to start if another copy is already running. Two copies polling
    getUpdates at once get HTTP 409 errors from Telegram and lose messages.

    Returns the open file handle. It has to stay referenced for the life of
    the process: closing it, or letting it get garbage collected, releases
    the lock.
    """
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Another copy of this bot is already running (%s is locked)." % LOCK_PATH)
    return lock_file


def with_defaults(cfg):
    """Fill in every setting a config can leave out. No token needed, so
    try_chat.py can build a working config without one."""
    cfg.setdefault("nudge_hour", 16)
    cfg.setdefault("nudge_minute", 30)
    cfg.setdefault("allowed_chat_ids", [])
    cfg.setdefault("llm_mode", False)
    # "openrouter", "anthropic" (Claude), "openai" (ChatGPT) or "ollama".
    # Each install uses its own keys, never anyone else's.
    cfg.setdefault("llm_provider", "openrouter")
    cfg.setdefault("openrouter_api_key", "")
    cfg.setdefault("llm_model", "anthropic/claude-haiku-4.5")
    cfg.setdefault("anthropic_api_key", "")
    cfg.setdefault("anthropic_model", "claude-haiku-5-5")
    cfg.setdefault("openai_api_key", "")
    cfg.setdefault("openai_model", "gpt-4o-mini")
    cfg.setdefault("ollama_base_url", "http://localhost:11434/v1")
    # Must read photos AND call tools: llama3.2-vision reads photos but has
    # no tool calling, so it could never log the food it saw.
    cfg.setdefault("ollama_model", "qwen3-vl:8b")
    return cfg


def _placeholder(token):
    return not token or "PUT_YOUR" in token


def load_config():
    # A single, clearly marked line, not a paragraph: under a launchd
    # crash loop this repeats every ThrottleInterval seconds, and status.sh
    # only shows the tail of the log, so the reason it keeps restarting has
    # to be readable in one line, not buried mid-paragraph.
    #
    # TELEGRAM_BOT_TOKEN stands in for the token where there is no file to
    # edit, such as a cloud session with the token stored as a secret. A real
    # token in config.json still wins.
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    elif not env_token:
        sys.exit("! No config.json found. Copy config.example.json to "
                 "config.json and put your bot token in it (from @BotFather "
                 "in Telegram: /newbot), or set TELEGRAM_BOT_TOKEN.")
    if env_token and _placeholder(cfg.get("token")):
        cfg["token"] = env_token
    if _placeholder(cfg.get("token")):
        sys.exit("! config.json has no real token in it yet.")
    with_defaults(cfg)
    if cfg["llm_mode"] and not cfg["allowed_chat_ids"]:
        # Open to anyone, with every message going to a paid model: anyone
        # who found the bot could spend the owner's money.
        sys.exit("! llm_mode is on but allowed_chat_ids is empty, so anyone "
                 "could use AI on your key. Add your chat id to allowed_chat_ids.")
    provider = cfg["llm_provider"]
    if cfg["llm_mode"] and provider not in llm_agent.API_KEYS and provider != "ollama":
        sys.exit("! llm_provider %r is not one of openrouter, anthropic, openai, "
                 "ollama." % provider)
    key_field = llm_agent.API_KEYS.get(provider)
    if cfg["llm_mode"] and key_field and _placeholder(cfg.get(key_field)):
        sys.exit("! llm_mode is on with llm_provider %s, but %s is not set in "
                 "config.json." % (provider, key_field))
    return cfg


def owner(cfg):
    """The first allowed chat id. It invites, lists members, and loads seed."""
    return cfg["allowed_chat_ids"][0] if cfg["allowed_chat_ids"] else None


def allowed(con, cfg, chat_id):
    """In config.json, or let in by an invite. An empty list is open to all."""
    return (not cfg["allowed_chat_ids"] or chat_id in cfg["allowed_chat_ids"]
            or fridge.is_member(con, chat_id))


# Model calls a day for anyone but the owner. A message can take several
# calls, so this is roughly 50 to 100 messages: plenty for real use, and a
# ceiling on what a runaway chat or a hijacked account can spend. Past it,
# they get the regular bot until tomorrow.
AI_DAILY_CALLS = 200


def ai_for(con, cfg, chat_id):
    """Whether this chat's messages go to the model.

    llm_mode turns the AI on for the bot. It then covers the chats in
    config.json (or everyone, on an open bot), since those were let in by
    hand. Someone who joined by invite starts without it, because every
    message costs the owner money and goes to a third party: the owner
    turns it on for them in /members.
    """
    if not cfg["llm_mode"]:
        return False
    if chat_id == owner(cfg):
        return True
    if fridge.calls_today(con, chat_id) >= AI_DAILY_CALLS:
        return False
    if not cfg["allowed_chat_ids"] or chat_id in cfg["allowed_chat_ids"]:
        return True
    return fridge.get_pref(con, chat_id, "ai") == "on"


def recipes_for(cfg, chat_id):
    """Recipes are the owner's own Apple Notes. Nobody else's to search, and
    on an open bot, with no owner, nobody's."""
    return owner(cfg) is not None and chat_id == owner(cfg)


def run_ai(con, chat_id, text, cfg, **kw):
    return llm_agent.run_agent(con, chat_id, text, cfg,
                               recipes=recipes_for(cfg, chat_id), **kw)


# --- telegram --------------------------------------------------------------

class Telegram:
    def __init__(self, token):
        self._token = token

    def _redact(self, text):
        """The token is never logged. Some urllib exceptions embed the
        request URL in their own message, and the URL carries the token."""
        return text.replace(self._token, "<token>") if self._token in text else text

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
            print("! telegram %s failed: %s %s" % (method, e.code, self._redact(body)))
        except Exception as e:                     # network blips are expected
            print("! telegram %s failed: %s" % (method, self._redact(str(e))))
        return None

    def send(self, chat_id, text, buttons=None, html=False):
        """html=True is only for messages carrying a pre block.

        Telegram uses a proportional font unless told otherwise, which breaks
        a card's columns. Nothing else asks for HTML, because
        turning it on means hand-escaping any stray angle bracket in a food
        name, and food names come from users.
        """
        params = {"chat_id": chat_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def answer(self, callback_id, text=None):
        self.call("answerCallbackQuery", callback_query_id=callback_id,
                  **({"text": text} if text else {}))

    def edit(self, chat_id, message_id, text, buttons=None, html=False):
        """Leaving buttons out removes the keyboard, which is how a closed
        item loses its row."""
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        self.call("editMessageText", **params)

    def set_buttons(self, chat_id, message_id, buttons):
        """Swap only the keyboard: picking an item on a card changes what
        can be tapped, not what the card says."""
        self.call("editMessageReplyMarkup", chat_id=chat_id,
                  message_id=message_id,
                  reply_markup={"inline_keyboard": buttons or []})

    def download_photo(self, file_id, timeout=REQUEST_DOWNLOAD_TIMEOUT):
        """The actual image bytes for a photo, or None on any failure.
        Two calls: getFile resolves file_id to a path, then the file itself
        lives on a different host entirely (api.telegram.org/file/..., not
        the regular bot API endpoint call() uses)."""
        info = self.call("getFile", file_id=file_id)
        if not info or not info.get("ok"):
            return None
        file_path = info["result"]["file_path"]
        url = FILE_API % (self._token, file_path)
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            print("! telegram file download failed: %s" % self._redact(str(e)))
            return None


# --- conversation ----------------------------------------------------------

WELCOME = (
    "I help you use food before it goes bad.\n\n"
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
    "/freezer: what you froze, and how it ended up\n"
    "/month: what you used in time, and what went in the bin\n"
    "/undo: take back the last list I added\n"
    "\"those are pantry\": move the last list out of tracking\n"
    "/clear: wipe everything and start over\n"
    "/privacy: what I keep, and who can see it\n"
    "/deleteme: delete everything I have about you\n"
    "/help: this"
)

CLEAR_ASK = ("This wipes everything: what's tracked and what's in your pantry. "
             "There is no getting it back.")


def handle_seed(tg, con, chat_id):
    """Load seed.json into this chat. Refuses if the chat already has anything,
    so a stray /seed can't quietly duplicate a real fridge.

    Sorted the same way a typed capture is: this used to insert every entry
    straight into the tracked table with no pantry or outside check at all,
    so a seed file full of real pantry contents (salt, spices, canned soup,
    bouillon) tracked all of it with a fake fridge date and put it in the
    daily nudge. A trailing "?" some import left on an uncertain name is
    stripped too, rather than shown to the user as-is.
    """
    path = os.path.join(HERE, "seed.json")
    if not os.path.exists(path):
        tg.send(chat_id, "No seed.json here.")
        return
    if fridge.open_items(con, chat_id):
        tg.send(chat_id, "You already have things tracked. I won't seed over them.")
        return
    with open(path) as f:
        data = json.load(f)
    today = date.today().isoformat()
    n_pantry = 0
    for it in data.get("items", []):
        name = it["name"].strip().rstrip(" ?").strip()
        if not name:
            continue
        skip, reason = sl.not_tracked(name)
        if skip:
            fridge.remember(con, chat_id, name, reason, date.today())
            n_pantry += 1
            continue
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
            " VALUES (?,?,?,?,0,?, 'open')",
            (chat_id, name, it["use_by"], it["risk"], today))
    con.commit()
    tail = ("\n\n%d went straight to your pantry, no dates: /pantry to see "
            "them." % n_pantry) if n_pantry else ""
    tg.send(chat_id, "Loaded your current fridge.\n\n"
            + fridge.compose_inventory(fridge.open_items(con, chat_id)) + tail)


COMMANDS = [
    ("fridge", "What's tracked, soonest first"),
    ("nudge", "What needs using right now"),
    ("pantry", "What I remember but don't track"),
    ("freezer", "What you froze, and how it ended up"),
    ("month", "What you used in time, and what got tossed"),
    ("undo", "Take back the last list"),
    ("setup", "Run the setup again"),
    ("clear", "Wipe your fridge and pantry"),
    ("privacy", "What I keep, and who can see it"),
    ("deleteme", "Delete everything I have about you"),
    ("help", "What I can do"),
]

OWNER_COMMANDS = [
    ("invite", "Make a one-use link for a friend"),
    ("members", "Who has joined, and remove them"),
    ("usage", "What AI mode used, per person"),
]


def send_card(tg, con, chat_id, kind, head, items, today, notes=None):
    """One card for these items, remembered so a tap can redraw it.

    This used to be one summary plus one buttoned message per item: three
    things at risk was four notifications. See card.py for the shape.
    """
    shown, more = items[:card.MAX_ITEMS], max(0, len(items) - card.MAX_ITEMS)
    spec = {"kind": kind, "head": head, "day": today.isoformat(),
            "ids": [i["id"] for i in shown], "more": more,
            "used_before": fridge.count_closed(con, chat_id, "used"),
            "notes": notes or [],
            "pick": _picks(kind, shown, today)}
    html, buttons = _render(kind, head, shown, today, more, notes=notes,
                            pick=spec["pick"])
    res = tg.send(chat_id, html, buttons=buttons, html=True)
    msg_id = ((res or {}).get("result") or {}).get("message_id")
    if msg_id is not None:
        fridge.save_card(con, chat_id, msg_id, spec)
    return len(shown)


def close_card(con, chat_id, spec):
    """The milestone line under a finished card, or None.

    Only when this card's taps crossed a milestone: a line on every finished
    card would be noise, and the card's own ticks already say what happened.
    """
    used_now = fridge.count_closed(con, chat_id, "used")
    crossed = [m for m in MILESTONES if spec["used_before"] < m <= used_now]
    return card.esc(milestone_line(crossed[-1])) if crossed else None


def _actionable(kind, today):
    """Which open items on this kind of card get buttons of their own.

    A nudge is all decisions. /fridge only asks about what's past its date or
    due tonight or tomorrow; the rest sit behind "Mark another item". The card
    after adding food asks nothing: it was bought a moment ago.
    """
    if kind == "fridge":
        return lambda i: sl.tier(i["use_by_date"], today) <= 1
    return None


def _picks(kind, items, today):
    """Whether a card starts as one row of numbers: more than DIRECT_MAX
    items with buttons of their own. Decided once, when it is sent."""
    act = _actionable(kind, today) or (lambda i: True)
    return sum(1 for i in items if not card.settled(kind, i) and act(i)) \
        > card.DIRECT_MAX


def _render(kind, head, items, today, more, closing=None, notes=None,
            pick=None):
    footer = card.tally("fridge" if kind == "added" else kind, items, more)
    if kind == "freezer":
        return card.render_freezer(head, items, footer, pick=pick)
    html, buttons = card.render(head, items, today, footer, closing,
                                label_one_tier=(kind != "nudge"), notes=notes,
                                actionable=_actionable(kind, today),
                                pick=pick)
    return html, (None if kind == "added" else buttons)


def refresh_card(tg, con, chat_id, message_id, spec):
    """Redraw a card after a tap: the line flips, its buttons go."""
    items = fridge.items_by_ids(con, chat_id, spec["ids"])
    today = date.fromisoformat(spec["day"])
    closing = None
    # The freezer gets no closing line: its last tap is as likely to be a
    # toss as not.
    if (spec["kind"] != "freezer" and items
            and all(card.settled(spec["kind"], i) for i in items)):
        closing = close_card(con, chat_id, spec)
    html, buttons = _render(spec["kind"], spec["head"], items, today,
                            spec["more"], closing, notes=spec.get("notes"),
                            pick=spec.get("pick"))
    tg.edit(chat_id, message_id, html, buttons=buttons, html=True)


def send_nudge(tg, con, chat_id, today=None):
    """What's at risk, as one card. Returns how many items it shows."""
    today = today or date.today()
    items = fridge.at_risk(con, chat_id, today)
    if not items:
        return 0
    return send_card(tg, con, chat_id, "nudge",
                     card.nudge_title(items, today), items, today)


def send_fridge(tg, con, chat_id, today=None):
    today = today or date.today()
    items = fridge.open_items(con, chat_id)
    if not items:
        tg.send(chat_id, fridge.compose_inventory(items))
        return
    send_card(tg, con, chat_id, "fridge", "In your fridge", items, today)


def _capped_item_list(names, max_chars=MAX_CAPTION_LIST_CHARS):
    """A comma-joined list, capped so a pantry can't grow a caption past
    Telegram's hard message length limit. Truncating the finished HTML at
    send time would risk cutting a message off mid-tag; capping the list
    itself, while it is still plain names, can't ever produce a broken
    tag."""
    joined = ", ".join(names)
    if len(joined) <= max_chars:
        return joined
    kept, total = [], 0
    for name in names:
        add = len(name) + (2 if kept else 0)  # ", " between items
        if total + add > max_chars:
            break
        kept.append(name)
        total += add
    return "%s, and %d more" % (", ".join(kept), len(names) - len(kept))


def send_freezer(tg, con, chat_id, today=None):
    """What is in the freezer, as one card with ✅ and 🗑 per item.

    This exists because freezing was a dead end: the item left every view and
    could never be answered for again, so a frozen rescue could never be
    reversed and the rescued figure could only drift upward.
    """
    today = today or date.today()
    items = fridge.frozen_items(con, chat_id)
    if not items:
        tg.send(chat_id, "Nothing in the freezer that I know about. "
                         "Freezing something from a nudge puts it here.")
        return 0
    return send_card(tg, con, chat_id, "freezer", "In the freezer", items, today)


def send_pantry(tg, con, chat_id, head="In your pantry"):
    """The pantry as a card, the same shape as every other list. It used to
    be the one list drawn differently."""
    items = fridge.pantry_items(con, chat_id)
    if not items:
        tg.send(chat_id, fridge.compose_pantry(items))
        return
    tg.send(chat_id, card.render_pantry(
        head, _capped_names([i["name"] for i in items if i["kind"] == "stable"]),
        _capped_names([i["name"] for i in items if i["kind"] == "outside"])),
        html=True)


def _capped_names(names, max_chars=MAX_CAPTION_LIST_CHARS):
    """_capped_item_list's cap, as a list of names for a card."""
    capped = _capped_item_list(names, max_chars)
    if capped == ", ".join(names):
        return names
    kept, _, more = capped.rpartition(", and ")
    return kept.split(", ") + ["and " + more]


# "What's in my fridge?" and nothing more: a request for the list, which is
# a card. Anything after the place ("...that I should use first?") or any
# other opening ("is the milk in the fridge ok?") is a question about the
# contents, and stays with the model.
_LISTING_RE = re.compile(
    r"^\s*(what'?s|what is|what do i have|what have i got|show(\s+me)?|list)"
    r"\s+(in\s+)?(my|the)\s+(fridge|freezer|pantry|cupboard)\s*[?.!]*\s*$",
    re.I)


def handle_listing_question(tg, con, chat_id, text):
    """Answer "what's in my fridge?" with the card, as /fridge does. True if
    handled. With AI on, the model used to answer in prose, so the same
    question looked different from the command."""
    m = _LISTING_RE.match(text)
    if not m:
        return False
    place = m.group(5).lower()
    if place == "fridge":
        send_fridge(tg, con, chat_id)
    elif place == "freezer":
        send_freezer(tg, con, chat_id)
    else:
        send_pantry(tg, con, chat_id)
    return True


FRIDGE_LISTING_PHRASES = ("in my fridge", "in the fridge")
PANTRY_LISTING_PHRASES = ("in my pantry", "in the pantry", "in my cupboard",
                          "in the cupboard")


def answer_question(tg, con, chat_id, text):
    """A genuine question about contents gets the real listing, not a
    definition. "Is there anything in my fridge" asks what's there, not what
    "fridge" means, and answering with the actual list is strictly more
    useful than the glossary line for the word itself."""
    n = text.lower()
    if any(p in n for p in FRIDGE_LISTING_PHRASES):
        send_fridge(tg, con, chat_id)
        return
    if any(p in n for p in PANTRY_LISTING_PHRASES):
        send_pantry(tg, con, chat_id)
        return
    tg.send(chat_id, fridge.answer_question(text))


def run_onboarding(tg, con, chat_id, text, cfg):
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

    if stage == "3":
        # Only a button answers this step; there is no reliable time to parse
        # from free text. Taking any typed text as a grocery list used to
        # force-end onboarding on it: "ignored, buttons only" got tracked as
        # two fake fridge items and setup silently stopped.
        tg.send(chat_id, "Tap one of the times above, or /skip.",
                buttons=onb.TIME_BUTTONS)
        return

    # No other step is left waiting on a message (step 4 resolves inside the
    # same callback that sets it), so this is unexpected. End onboarding
    # defensively rather than leaving the chat stuck, and handle the text
    # normally.
    onb.set_step(con, chat_id, onb.DONE)
    handle_message(tg, con, {"chat": {"id": chat_id}, "text": text}, cfg)


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
    today = today or date.today()
    send_card(tg, con, chat_id, "nudge", card.nudge_title(items[:1], today),
              items[:1], today)


# --- rendering an LLM reply -------------------------------------------------
#
# The model writes plain markdown (**bold**, *italic*, `code`) and, when
# asked to list more than one thing, "- " bulleted lines (the system prompt
# asks for exactly this). Telegram needs HTML to render any of it: bulleted
# lines become plain "•" lines, and everything gets ordinary inline markdown.

_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_USES_RE = re.compile(r"^Uses (your|mostly) ")


_TAG_RE = re.compile(r"</?(b|i|code)>")


def _tags_are_balanced(html):
    """Whether every open tag this line introduced closes in the right order.

    Bold and italic are converted independently, so markdown that crosses
    its own boundaries ("**bold *italic** more*") can produce tags that
    interleave instead of nest: <b>bold <i>italic</b> more</i>. Telegram's
    parser rejects that outright and fails the whole message, not just the
    one line, so this has to be caught before it ever reaches send().
    """
    stack = []
    for m in _TAG_RE.finditer(html):
        tag = m.group(1)
        if m.group(0)[1] == "/":
            if not stack or stack.pop() != tag:
                return False
        else:
            stack.append(tag)
    return not stack


def _inline_markdown(escaped_line):
    line = re.sub(r"(\*\*|__)(.+?)\1", r"<b>\2</b>", escaped_line)
    line = re.sub(r"`([^`]+?)`", r"<code>\1</code>", line)
    line = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", line)
    line = re.sub(r"(?<!_)_(?!_)([^_\n]+?)_(?!_)", r"<i>\1</i>", line)
    # Overlapping emphasis markers can produce cross-nested tags (see
    # _tags_are_balanced). A line that can't be formatted safely is still
    # better sent plain, asterisks and all, than not sent at all.
    return line if _tags_are_balanced(line) else escaped_line


def _markdown_to_html(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Telegram has no heading or rule support at all: a "### Title" or a
        # standalone "---" line would otherwise show up as literal hash
        # marks or dashes rather than doing anything. A heading becomes
        # bold text instead; a rule is dropped outright, since a blank line
        # already does the separating job in a chat.
        if _HR_RE.match(line):
            i += 1
            continue
        header = _HEADER_RE.match(line)
        if header:
            blocks.append("<b>%s</b>" % _inline_markdown(card.esc(header.group(1))))
            i += 1
            continue
        # A recipe offer's dish name, the line above its "Uses your ...":
        # bold whether or not a small model kept the ** around it.
        if (i + 1 < len(lines) and _USES_RE.match(lines[i + 1])
                and line.strip() and not _BULLET_RE.match(line)):
            name = re.sub(r"^\*\*(.*)\*\*$", r"\1", line.strip())
            blocks.append("<b>%s</b>" % card.esc(name))
            i += 1
            continue
        if _BULLET_RE.match(line):
            # Plain "•" lines, not a <pre> block: Telegram draws <pre> as
            # code, with a copy icon, and a list of words has no columns
            # worth keeping. The cards are plain text too.
            item = _BULLET_RE.sub("", line, count=1)
            blocks.append("• " + _inline_markdown(card.esc(item)))
            i += 1
        else:
            blocks.append(_inline_markdown(card.esc(line)))
            i += 1
    return "\n".join(blocks)


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]+")


def _strip_emoji(text):
    """The bot's own messages carry no emoji, so the model's don't either.
    Asking the model is not enough with a small one; this makes it so."""
    text = _EMOJI_RE.sub("", text)
    return "\n".join(re.sub(r" {2,}", " ", line).rstrip()
                     for line in text.split("\n")).strip()


def send_llm_reply(tg, chat_id, text):
    """Falls back to the original, unformatted plain text if the converted
    HTML ever fails to send: a malformed tag from an imperfect conversion of
    free-form model text must never mean the user gets nothing back."""
    text = _strip_emoji(text) or text
    if tg.send(chat_id, _markdown_to_html(text), html=True) is None:
        tg.send(chat_id, text)


def _recipe_buttons(draft):
    # Named for what lands where: a recipe, in the Recipes folder.
    return [[{"text": "Save to Recipes", "callback_data": "recipe:save:%s" % draft["id"]},
             {"text": "Cancel", "callback_data": "recipe:cancel:%s" % draft["id"]}]]


def send_pending_recipe(tg, con, chat_id):
    """A recipe the model drafted this turn, shown with Save and Cancel.

    The tap is the confirmation, and it is handled here in code, not by the
    model: a recipe page that talks the model into "saving" gets no further
    than this preview. Plain text, not HTML, because every word of it came
    from a user or a web page."""
    draft = llm_agent.pending_recipe(con, chat_id)
    if not draft or draft.get("shown"):
        return
    if tg.send(chat_id, llm_agent.recipe_note_text(draft),
               buttons=_recipe_buttons(draft)):
        llm_agent.mark_recipe_shown(con, chat_id)


_LINK_RE = re.compile(r"https://\S+")
RECIPE_LINK_MAX_WORDS = 4


def recipe_link(text):
    """The one https link in a message that is mostly that link ("save this
    <link>"), or None. A link inside a longer message is a conversation
    about it, and stays with the model."""
    links = _LINK_RE.findall(text)
    if len(links) != 1:
        return None
    rest = _LINK_RE.sub(" ", text).split()
    return links[0] if len(rest) <= RECIPE_LINK_MAX_WORDS else None


def handle_recipe_link(tg, con, chat_id, text, cfg):
    """Draft a recipe from a link in code, before the model sees it. True if
    handled.

    Left to the model, a small one would often not call fetch_recipe_page
    at all and reply that it can't open links. Most recipe sites carry the
    recipe as structured data, which needs no model to read: this drafts it
    directly and shows the same Save and Cancel preview. A page with no
    structured recipe goes to the model with its text, when AI is on.
    Owner only, like every recipe action: the Notes are theirs.
    """
    if not recipes_for(cfg, chat_id):
        return False
    url = recipe_link(text)
    if not url:
        return False
    page = llm_agent.fetch_recipe_page(url)
    if page.get("error"):
        tg.send(chat_id, "%s Paste the ingredients and steps instead and I'll "
                         "draft it from those." % page["error"])
        return True
    if page.get("title"):
        show_recipe_draft(tg, con, chat_id, page)
        return True
    if ai_for(con, cfg, chat_id):
        send_llm_reply(tg, chat_id, run_ai(
            con, chat_id, "Draft this recipe for me to save. It's from %s, and "
            "the page says:\n\n%s" % (url, page.get("text", "")), cfg,
            user_text=text))
        send_pending_recipe(tg, con, chat_id)
        return True
    tg.send(chat_id, "I couldn't find a recipe on that page that I can read "
                     "reliably. Paste the ingredients and steps instead.")
    return True


def show_recipe_draft(tg, con, chat_id, recipe):
    """The one way a recipe reaches the Save and Cancel preview from code,
    whether it came from a link or a paste, so both look and act the same."""
    result = llm_agent.exec_draft_recipe(con, chat_id, recipe, date.today())
    if result.get("error"):
        tg.send(chat_id, "I couldn't make a draft from that: it's either too "
                         "long to show in one message or has no ingredients I "
                         "can read. Try a shorter version.")
        return
    send_pending_recipe(tg, con, chat_id)


def handle_pasted_recipe(tg, con, chat_id, text, cfg):
    """A pasted recipe, or "save to notes" right after one, straight to the
    preview. True if handled.

    Left to the model, a pasted recipe got an ingredient check or a question,
    and "save to notes" got the recipe written back as chat text: never the
    buttons a link gets. Owner only, like every recipe action.
    """
    if not recipes_for(cfg, chat_id):
        return False
    recipe = recipe_text.parse(text)
    if recipe is None and recipe_text.is_save_request(text):
        for earlier in reversed(llm_agent.recent_messages(con, chat_id)):
            recipe = recipe_text.parse(earlier)
            if recipe:
                break
    if recipe is None:
        return False
    show_recipe_draft(tg, con, chat_id, recipe)
    return True


MAX_PHOTO_BYTES = 10 * 1024 * 1024
# Telegram keeps a 2560px copy of newer photos. A vision model is billed by
# pixels, and that copy costs about four times the 1280px one, which still
# reads a fridge shelf or a receipt.
MAX_PHOTO_EDGE = 1280


def _pick_photo(sizes):
    """Telegram sends several sizes of the same photo, smallest first. The
    largest one at or under the cap, rather than always the biggest: a huge
    photo still gets something sent instead of a flat refusal, and the model
    doesn't need more resolution than that to read a fridge or a receipt."""
    under_cap = [s for s in sizes if s.get("file_size", 0) <= MAX_PHOTO_BYTES
                 and max(s.get("width", 0), s.get("height", 0)) <= MAX_PHOTO_EDGE]
    return (under_cap[-1] if under_cap else sizes[0])["file_id"]


def handle_photo(tg, con, chat_id, msg, cfg):
    """A photo only means something in llm_mode: there is no way for the
    regex pipeline to read an image, and pretending otherwise would be the
    exact kind of silent guess this bot is built to avoid."""
    if not ai_for(con, cfg, chat_id):
        tg.send(chat_id, "I can't read photos yet, only typed lists: "
                         "commas between things.")
        return
    caption = (msg.get("caption") or "").strip()
    file_id = _pick_photo(msg["photo"])
    photo_bytes = tg.download_photo(file_id)
    if photo_bytes is None:
        tg.send(chat_id, "Couldn't get that photo from Telegram. Try sending it again.")
        return
    image_b64 = base64.b64encode(photo_bytes).decode()
    send_llm_reply(tg, chat_id, run_ai(con, chat_id, caption, cfg, image_b64=image_b64))
    send_pending_recipe(tg, con, chat_id)


INVITE_SPENT = ("That invite link has already been used or has expired. "
                "Ask whoever sent it for a new link.")


def join_by_invite(tg, con, msg):
    """Let a chat in if its message is "/start <code>" with a live code.

    This is how a t.me/<bot>?start=<code> link arrives. Returns True if the
    chat is now in, so the /start carries on into setup as usual. A bad code
    gets one line back, since the link already gave the bot away; a chat
    with no code at all still gets nothing.
    """
    text = (msg.get("text") or "").strip()
    parts = text.split()
    if len(parts) != 2 or parts[0].lower() != "/start":
        return False
    chat = msg["chat"]
    if fridge.redeem_invite(con, parts[1], chat["id"], chat.get("first_name")):
        return True
    tg.send(chat["id"], INVITE_SPENT)
    return False


def compose_members(con, cfg):
    """(text, buttons) for /members: who got in by invite, each removable,
    and, when the bot has AI at all, each with AI switchable."""
    people = fridge.members(con)
    if not people:
        return ("Nobody has joined by invite yet. /invite makes a link.", None)
    lines = ["Joined by invite (%d). Removing someone ends their access and "
             "their nudges; their data stays." % len(people)]
    if cfg["llm_mode"]:
        lines.append("AI on means their messages go to the model on your "
                     "key. Your recipes stay yours either way.")
    lines.append("")
    buttons = []
    for p in people:
        name = p["name"] or "chat %d" % p["chat_id"]
        on = ai_for(con, cfg, p["chat_id"])
        lines.append("  • %s, joined %s%s" % (
            name, p["joined"][:10],
            (", AI on" if on else ", AI off") if cfg["llm_mode"] else ""))
        row = [{"text": "Remove %s" % name,
                "callback_data": "member:remove:%d" % p["chat_id"]}]
        if cfg["llm_mode"]:
            row.append({"text": "Turn AI off" if on else "Turn AI on",
                        "callback_data": "member:ai:%d" % p["chat_id"]})
        buttons.append(row)
    return "\n".join(lines), buttons


def privacy_note(con, cfg, chat_id):
    """What is kept and who can see it, in plain words.

    The AI line only appears for someone whose messages actually go to a
    model, and says where: a person with AI off is not told about a service
    that never sees their messages.
    """
    if not ai_for(con, cfg, chat_id):
        ai = ("Apart from Telegram delivering them, your messages go "
              "nowhere else.")
    elif cfg["llm_provider"] == "ollama":
        ai = ("Your messages and photos are read by an AI model running on "
              "that same computer, not sent anywhere else.")
    else:
        company = llm_agent.PROVIDER_NAMES.get(cfg["llm_provider"], "the AI service")
        ai = ("Your messages and photos are also sent to an AI service "
              "(%s) so they can be understood. It keeps them under its own "
              "policy, which /deleteme can't reach." % company)
    # Named when Telegram gave us a name: the data lives on the owner's
    # computer, so "I keep" blurs the bot with the person running it.
    name = cfg.get("bot_name")
    return (("What %s keeps, and who can see it:\n\n" % name if name
             else "What I keep, and who can see it:\n\n") +
            "  • The food you send%s, what happened to it, and your "
            "settings.\n" % ("" if name else " me") +
            "  • It's stored on the computer of whoever runs this bot, not "
            "in the cloud, and they can see it.\n"
            "  • %s\n\n"
            "/deleteme removes all of it, any time. /privacy shows this "
            "again." % ai)


DELETE_ASK = ("This deletes everything I have about you: your fridge, pantry "
              "and freezer, your settings, and your history. It can't be "
              "undone.")


KEEPS_RECIPES = ("\n\nRecipes you saved stay in your Recipes folder in "
                 "Notes: this never touches Notes.")


def handle_account_command(tg, con, chat_id, text, cfg):
    """/privacy and /deleteme. True if handled.

    Ahead of AI mode for the same reason as the owner commands: someone
    asking what is kept, or to be deleted, must get the real answer and the
    real button, not the model's paraphrase of one.
    """
    low = text.lower()
    if low.startswith("/privacy"):
        tg.send(chat_id, privacy_note(con, cfg, chat_id))
        return True
    if low.startswith("/deleteme"):
        # Only the owner can save recipes, so only the owner could wonder.
        ask = DELETE_ASK + (KEEPS_RECIPES if recipes_for(cfg, chat_id) else "")
        tg.send(chat_id, ask, buttons=[[
            {"text": "Delete my data", "callback_data": "deleteme:yes"},
            {"text": "Cancel", "callback_data": "deleteme:no"},
        ]])
        return True
    return False


def handle_owner_command(tg, con, chat_id, text, cfg):
    """/invite and /members, from the owner's chat only. True if handled.

    Runs ahead of AI mode, which otherwise takes every message, slash
    commands included: these are the owner managing the bot, not a
    conversation about food.
    """
    if chat_id != owner(cfg):
        return False
    low = text.lower()
    if low.startswith("/invite"):
        code = fridge.create_invite(con)
        tg.send(chat_id, "Send this to one person. It lets them in once and "
                         "stops working after %d days:\n\nhttps://t.me/%s?start=%s"
                % (fridge.INVITE_DAYS, cfg.get("bot_username") or "<your bot>",
                   code))
        return True
    if low.startswith("/members"):
        text, buttons = compose_members(con, cfg)
        tg.send(chat_id, text, buttons=buttons)
        return True
    if low.startswith("/usage"):
        tg.send(chat_id, compose_usage(con, cfg))
        return True
    return False


def compose_usage(con, cfg, today=None):
    """What AI mode used, per person, this week and this month."""
    today = today or date.today()
    names = {m["chat_id"]: m["name"] or "chat %d" % m["chat_id"]
             for m in fridge.members(con)}
    names[owner(cfg)] = "you"

    def block(title, since):
        rows = fridge.usage_since(con, since)
        if not rows:
            return ["%s: no AI calls." % title]
        out = ["%s:" % title]
        for r in rows:
            cost = ("$%.4f" % r["cost"] if r["cost"] is not None
                    else "cost not reported")
            out.append("  • %s: %d call%s, %s in / %s out, %s" % (
                names.get(r["chat_id"], "chat %d" % r["chat_id"]),
                r["calls"], "" if r["calls"] == 1 else "s",
                format(r["prompt_tokens"], ","),
                format(r["completion_tokens"], ","), cost))
        return out

    lines = block("Last 7 days", today - timedelta(days=6))
    lines += [""] + block(today.strftime("%B so far"), today.replace(day=1))
    lines += ["", "Tokens and cost as the provider reported them. A message "
                  "can take several calls when the model uses tools."]
    return "\n".join(lines)


def handle_message(tg, con, msg, cfg):
    chat_id = msg["chat"]["id"]
    # A flood gets nothing back, quietly, before any other work runs.
    if _rate_limited(chat_id):
        return
    # In a group, anyone in it could /clear the shared fridge, and the daily
    # nudge would go out to everyone in the group.
    if msg["chat"].get("type") != "private":
        return
    # A reply confirms the bot exists, so a chat that isn't on the allow
    # list gets nothing at all, not even an error. The one exception is a
    # chat holding an invite link: it already knows the bot exists.
    if not allowed(con, cfg, chat_id):
        # Someone removed from the bot can still delete what it kept about
        # them: /privacy promises that, any time. Nothing else gets through.
        if ((msg.get("text") or "").strip().lower().startswith("/deleteme")
                and fridge.has_data(con, chat_id)):
            handle_account_command(tg, con, chat_id, msg["text"].strip(), cfg)
            return
        if not join_by_invite(tg, con, msg):
            return
    if "photo" in msg:
        handle_photo(tg, con, chat_id, msg, cfg)
        return
    text = (msg.get("text") or "").strip()
    if not text:
        tg.send(chat_id, "I can only read typed lists for now: "
                         "commas between things.")
        return
    if len(text) > MAX_MESSAGE_LENGTH:
        tg.send(chat_id, "That is too long for me to read in one go. Send it "
                         "in a few smaller messages.")
        return

    # llm_mode is a separate, self-contained conversational front end: a
    # message here never reaches onboarding, is_chatter, correction or
    # parse_list. It replaces how a typed message is understood, not the
    # daily nudge or the used/frozen/tossed buttons, which are unchanged in
    # both modes since they are not an understanding problem.
    if handle_owner_command(tg, con, chat_id, text, cfg):
        return
    if handle_account_command(tg, con, chat_id, text, cfg):
        return
    # Setup is the bot's own conversation, with or without AI: /start,
    # /setup and /skip, and every answer while a step is waiting. Without
    # this, AI mode took /start too, so anyone with AI on never saw setup
    # or the privacy note.
    in_setup = (text.lower().startswith(("/start", "/setup", "/skip"))
                or (onb.active(con, chat_id) and not text.startswith("/")))
    if not in_setup and (handle_recipe_link(tg, con, chat_id, text, cfg)
                         or handle_pasted_recipe(tg, con, chat_id, text, cfg)
                         or handle_listing_question(tg, con, chat_id, text)):
        return
    # Commands are the bot's, always. They used to go to the model with AI
    # on, so a tap on /fridge in the menu got prose instead of the card, and
    # the same tap looked different depending on a setting.
    if ai_for(con, cfg, chat_id) and not in_setup and not text.startswith("/"):
        send_llm_reply(tg, chat_id, run_ai(con, chat_id, text, cfg))
        send_pending_recipe(tg, con, chat_id)
        return

    # A reply to me or a genuine question can arrive at any point, onboarding
    # included, and answering it must never look like a captured fridge item.
    # Before this existed, "what's toss?" became a tracked item with a fake
    # date on it, which is the exact confusion the bot exists to prevent.
    if not text.startswith("/"):
        if fridge.is_chatter(text):
            tg.send(chat_id, "Noted. Send a list whenever you want to add "
                             "something, or /help for what I can do.")
            return
        if fridge.is_question(text):
            answer_question(tg, con, chat_id, text)
            return

    # While onboarding is running it owns plain text, because each step is a
    # question and the answer means something different at each one.
    if onb.active(con, chat_id) and not text.startswith("/"):
        run_onboarding(tg, con, chat_id, text, cfg)
        return

    low = text.lower()
    if low.startswith("/start"):
        # A first /start onboards. A later one does not restart it: someone
        # tapping /start out of curiosity should not lose their fridge.
        if not onb.started(con, chat_id):
            tg.send(chat_id, privacy_note(con, cfg, chat_id))
            # With AI on, a photo can be read, so the opening asks for the
            # least work there is: the next receipt. /setup still runs the
            # four steps for anyone who wants them.
            opening = (onb.begin_receipt_first if ai_for(con, cfg, chat_id)
                       else onb.begin)
            tg.send(chat_id, opening(con, chat_id, cfg.get("bot_name")))
        else:
            tg.send(chat_id, WELCOME)
        return
    if low.startswith("/setup"):
        tg.send(chat_id, onb.begin(con, chat_id, cfg.get("bot_name")))
        return
    if low.startswith("/skip"):
        tg.send(chat_id, onb.skip(con, chat_id, cfg["nudge_hour"]))
        return
    if low.startswith("/help"):
        tg.send(chat_id, HELP)
        return
    if low.startswith("/fridge"):
        send_fridge(tg, con, chat_id)
        return
    if low.startswith("/month"):
        fig = fridge.month_figures(con, chat_id)
        html = card.render_month(fig)
        if html:
            tg.send(chat_id, html, html=True)
        else:
            tg.send(chat_id, fridge.compose_month(fig))
        return
    if low.startswith("/freezer"):
        send_freezer(tg, con, chat_id)
        return
    if low.startswith("/pantry"):
        send_pantry(tg, con, chat_id)
        return
    if low.startswith("/undo"):
        send_undo(tg, con, chat_id)
        return
    if low.startswith("/clear"):
        tg.send(chat_id, CLEAR_ASK, buttons=[[
            {"text": "Wipe fridge and pantry", "callback_data": "clear:yes"},
            {"text": "Cancel", "callback_data": "clear:no"},
        ]])
        return
    if low.startswith("/seed"):
        # seed.json is the owner's real fridge. Anyone with nothing logged
        # could otherwise load it, which leaks personal data.
        if chat_id == owner(cfg):
            handle_seed(tg, con, chat_id)
        else:
            tg.send(chat_id, HELP)
        return
    if low.startswith("/nudge"):
        if send_nudge(tg, con, chat_id) == 0:
            # Said out loud: this is the state the whole system is trying to
            # produce, and silence here looks identical to the bot being broken.
            tg.send(chat_id, "Nothing needs using today.")
        return
    if low.startswith("/"):
        tg.send(chat_id, HELP)
        return

    # "I put butter chicken in the fridge as leftovers" is a capture written
    # as a sentence. It has to be read before the correction check, which
    # would otherwise see "fridge" and move the previous list.
    put = fridge.put_away(text)
    if put:
        names, too_long = [put], []
    else:
        # "these items are all from the pantry" is a correction, not an item.
        # Act on it rather than logging the sentence, which is what used to
        # happen.
        fix = fridge.correction(text)
        if fix:
            send_correction(tg, con, chat_id, fix)
            return

        # Any other sentence is prose. Logging it produces a dated fridge item
        # with a whole clause for a name, which then turns up in a nudge.
        if fridge.looks_like_sentence(text):
            tg.send(chat_id, "That reads like a sentence rather than a list, "
                             "so I haven't tracked it.\n\nFood goes in with "
                             "commas between: milk, spinach, chicken thighs. "
                             "If I sorted your last list wrong, say \"those are "
                             "pantry\" or \"those are fridge\" and I'll move "
                             "them.")
            return

        # "milk eggs bread" has no comma to split on, so without this it
        # becomes one tracked item named "milk eggs bread" with a fake date.
        if fridge.looks_like_an_unseparated_list(text):
            tg.send(chat_id, "Looks like a few different things with nothing "
                             "between them. Put commas between them and send "
                             "it again: milk, eggs, bread.")
            return

        names, too_long = fridge.parse_list(text, report=True)
    names, n_dropped = fridge.cap_names(names)

    if too_long:
        tg.send(chat_id, "These didn't look like food names, so I left them "
                         "out rather than guessing: " + "; ".join(too_long))

    if n_dropped:
        tg.send(chat_id, "That is more than I can take in one go, so I kept "
                         "the first %d and left out %d. Send the rest in a "
                         "second message." % (fridge.MAX_ITEMS, n_dropped))

    if not names:
        tg.send(chat_id, "I couldn't pick anything out of that. "
                         "Try: milk, spinach, chicken thighs")
        return

    if fridge.room_left(con, chat_id) <= 0:
        tg.send(chat_id, "Your fridge already has %d things tracked, the most "
                         "I keep. Mark some used or tossed from /fridge, then "
                         "send this again." % fridge.MAX_OPEN_ITEMS)
        return

    tracked, stable, outside, again = fridge.add_items(con, chat_id, names)
    send_capture(tg, con, chat_id, tracked, stable, outside, again)


def send_capture(tg, con, chat_id, tracked, stable, outside, again):
    """What a list turned into, as the same card /fridge shows.

    It used to be prose ("Tracking 2 things: ..."), so the same food looked
    one way when added and another in /fridge. Now it is the card, with the
    pantry and counter sorting said in a note underneath. Someone who sent
    only their spice rack gets the pantry card instead: the list went
    somewhere useful, it just was not the tracked pile.
    """
    notes = []
    if again:
        notes.append("Already had %s, so the date moved: %s."
                     % ("this" if len(again) == 1 else "these", ", ".join(again)))
    if stable:
        notes.append("Pantry, no nudges: %s." % ", ".join(stable))
    if outside:
        notes.append("Counter, no nudges: %s." % ", ".join(outside))
    added = {name for name, _, _, _ in tracked} | set(again)
    items = [i for i in fridge.open_items(con, chat_id) if i["name"] in added]
    if items:
        send_card(tg, con, chat_id, "added", "Added to your fridge", items,
                  date.today(), notes=notes)
    elif stable or outside:
        tg.send(chat_id, card.render_pantry(
            "Added to your pantry", _capped_names(stable), _capped_names(outside)),
            html=True)


def send_correction(tg, con, chat_id, target):
    """"Those are pantry" or "those are fridge", answered with the card for
    where things went. Nothing moved means an explanation, which stays text."""
    r = fridge.reclassify(con, chat_id, target)
    if not r["moved"]:
        tg.send(chat_id, r["message"])
        return
    if target == "fridge":
        moved = set(r["moved"])
        items = [i for i in fridge.open_items(con, chat_id) if i["name"] in moved]
        send_card(tg, con, chat_id, "fridge", "Moved to your fridge", items,
                  date.today())
        return
    notes = []
    if r["held"]:
        notes.append("Kept %s in the fridge. Raw meat and fish stay "
                     "watched; /undo removes it." % ", ".join(r["held"]))
    tg.send(chat_id, card.render_pantry("Moved to your pantry",
                                        _capped_names(r["moved"]), [], notes),
            html=True)


def send_undo(tg, con, chat_id):
    """/undo, answered with a card naming what was taken back."""
    r = fridge.undo(con, chat_id)
    if not (r["tracked"] or r["pantry"]):
        tg.send(chat_id, r["message"])
        return
    tg.send(chat_id, card.render_list(
        "Took back your last list",
        [("Tracked", _capped_names(r["tracked"])),
         ("Pantry", _capped_names(r["pantry"]))],
        "Removed. Nothing kept."), html=True)


def handle_pick(tg, con, chat_id, cb, msg, state, raw_id):
    """Tap a number, then choose: the keyboard swaps, the card doesn't.

    pick:<id> shows that item's choices, pickall shows a number for every
    open item (behind "Mark another item"), unpick goes back to the card's own
    buttons. The choice itself is an ordinary used:/frz: tap, which closes
    the item and redraws the card with its normal buttons.
    """
    spec = fridge.load_card(con, chat_id, msg.get("message_id", 0))
    if not spec:
        tg.answer(cb["id"], "That list is out of date. Send it again.")
        return
    freezer = spec["kind"] == "freezer"
    items = fridge.items_by_ids(con, chat_id, spec["ids"])
    numbered = [(n, i) for n, i in enumerate(items, 1)
                if not card.settled(spec["kind"], i)]
    if state == "unpick":
        _, buttons = _render(spec["kind"], spec["head"], items,
                             date.fromisoformat(spec["day"]), spec["more"],
                             notes=spec.get("notes"), pick=spec.get("pick"))
    elif state == "pickall":
        buttons = card.picker(numbered)
    else:
        try:
            want = int(raw_id)
        except ValueError:
            tg.answer(cb["id"])
            return
        match = [(n, i) for n, i in numbered if i["id"] == want]
        if not match:
            tg.answer(cb["id"], "Already handled.")
            return
        buttons = card.actions(match[0][0], match[0][1], freezer)
    tg.answer(cb["id"])
    tg.set_buttons(chat_id, msg["message_id"], buttons)


def handle_callback(tg, con, cb, cfg):
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if ":" not in data or chat_id is None:
        tg.answer(cb["id"])
        return
    if msg.get("chat", {}).get("type") != "private":
        return
    # Taps share the message budget: a forged stream of callbacks costs
    # sends and writes the same as a flood of messages.
    if _rate_limited(chat_id):
        return
    if not allowed(con, cfg, chat_id) and not (
            data.startswith("deleteme:") and fridge.has_data(con, chat_id)):
        return
    state, _, raw_id = data.partition(":")
    if state in ("pick", "pickall", "unpick"):
        handle_pick(tg, con, chat_id, cb, msg, state, raw_id)
        return
    if state == "recipe":
        handle_recipe_callback(tg, con, chat_id, cb, msg, raw_id, cfg)
        return

    if state == "member":
        action, _, raw = raw_id.partition(":")
        if chat_id != owner(cfg) or action not in ("remove", "ai"):
            tg.answer(cb["id"])
            return
        try:
            who = int(raw)
        except ValueError:
            tg.answer(cb["id"])
            return
        if action == "remove":
            fridge.remove_member(con, who)
            tg.answer(cb["id"], "Removed.")
        elif fridge.is_member(con, who):
            on = fridge.get_pref(con, who, "ai") == "on"
            fridge.set_pref(con, who, "ai", "off" if on else "on")
            tg.answer(cb["id"], "AI off." if on else "AI on.")
        else:
            tg.answer(cb["id"])
        text, buttons = compose_members(con, cfg)
        tg.edit(chat_id, msg["message_id"], text, buttons=buttons)
        return

    if state == "frz":
        outcome, _, raw = raw_id.partition(":")
        if outcome not in ("used", "tossed"):
            tg.answer(cb["id"])
            return
        try:
            item_id = int(raw)
        except ValueError:
            tg.answer(cb["id"])
            return
        row = con.execute("SELECT name, tier FROM items WHERE id=? AND chat_id=?"
                          " AND state='frozen' AND freezer_outcome IS NULL",
                          (item_id, chat_id)).fetchone()
        if not row:
            tg.answer(cb["id"], "Already handled.")
            return
        fridge.settle_freezer_item(con, chat_id, item_id, outcome)
        tg.answer(cb["id"], "Used it" if outcome == "used" else "Tossed it")

        spec = fridge.load_card(con, chat_id, msg["message_id"])
        if spec and item_id in spec["ids"]:
            refresh_card(tg, con, chat_id, msg["message_id"], spec)
            return

        # A message sent before the freezer was a card: one item, its own
        # buttons, and the reversal said as a separate line.
        if outcome == "used":
            tg.edit(chat_id, msg["message_id"],
                    "%s: used out of the freezer." % row["name"])
            return
        # A reversal: the food was wasted in the end (§19). No verdict on it: "freezing only to bin it
        # later is not a save" is doctrine written for the model, not a line to
        # say to the person, and as a message it is guilt, which §20 forbids
        # outright. State what happened to the figure and stop.
        tg.edit(chat_id, msg["message_id"],
                "%s: tossed out of the freezer." % row["name"])
        if fridge.is_rescue("frozen", row["tier"]):
            tg.send(chat_id, "Noted. That one had counted as used in time, so "
                             "it comes off this month's figure.")
        else:
            tg.send(chat_id, "Noted. Logged so the monthly count is honest.")
        return

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
        if not (0 <= hour <= 23):
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

    if state == "deleteme":
        if raw_id != "yes":
            tg.answer(cb["id"], "Kept.")
            tg.edit(chat_id, msg["message_id"], "Nothing deleted.")
            return
        was_member = fridge.is_member(con, chat_id)
        n_items, n_pantry = fridge.delete_person(con, chat_id)
        tg.answer(cb["id"], "Deleted.")
        tail = (" You've also left this bot: you'd need a new invite to come "
                "back." if was_member else " Send /start to begin again.")
        tg.edit(chat_id, msg["message_id"],
                "Deleted %d tracked thing%s, %d pantry entr%s, your settings "
                "and your history.%s" % (
                    n_items, "" if n_items == 1 else "s",
                    n_pantry, "y" if n_pantry == 1 else "ies", tail))
        return

    if state == "clear":
        if raw_id != "yes":
            tg.answer(cb["id"], "Left it alone.")
            tg.edit(chat_id, msg["message_id"], "Nothing wiped.")
            return
        n_items, n_pantry = fridge.clear_chat(con, chat_id)
        tg.answer(cb["id"], "Wiped.")
        tg.edit(chat_id, msg["message_id"],
                "Wiped %d tracked thing%s and %d pantry entr%s. Send a list when "
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

    row = con.execute(
        "SELECT name FROM items WHERE id=? AND chat_id=? AND state='open'",
        (item_id, chat_id)).fetchone()
    if not row:
        tg.answer(cb["id"], "Already handled.")
        return

    fridge.close_item(con, chat_id, item_id, state)
    tg.answer(cb["id"], STATE_LABELS[state])

    spec = fridge.load_card(con, chat_id, msg["message_id"])
    if spec and item_id in spec["ids"]:
        refresh_card(tg, con, chat_id, msg["message_id"], spec)
        return

    # A message sent before cards existed: one item, its own buttons.
    tg.edit(chat_id, msg["message_id"], "%s: %s" % (row["name"], STATE_LABELS[state].lower()))

    if state == "tossed":
        tg.send(chat_id, "Noted.")
        return
    n = fridge.count_closed(con, chat_id, "used")
    if state == "used" and n in MILESTONES:
        tg.send(chat_id, milestone_line(n))
        return
    tg.send(chat_id, CLOSE_LINES[state])


def handle_recipe_callback(tg, con, chat_id, cb, msg, raw, cfg):
    """recipe:save:<id> or recipe:cancel:<id>. The id must match the
    current draft, so an old preview can't act on a newer one."""
    action, _, draft_id = raw.partition(":")
    draft = llm_agent.pending_recipe(con, chat_id)
    if not draft or draft.get("id") != draft_id:
        tg.answer(cb["id"], "That draft's gone.")
        tg.edit(chat_id, msg["message_id"],
                "That draft's gone. Send the recipe again if you still want it.")
        return
    if action == "cancel":
        llm_agent.clear_pending_recipe(con, chat_id)
        tg.answer(cb["id"], "Not saved.")
        tg.edit(chat_id, msg["message_id"], "Not saved: %s" % draft["title"])
        return
    if action != "save":
        tg.answer(cb["id"])
        return

    preview = llm_agent.recipe_note_text(draft)
    # Notes is the owner's alone. The allow-list can hold household chats
    # too, and an empty one means no owner at all, so neither is enough.
    if not recipes_for(cfg, chat_id):
        tg.answer(cb["id"], "Not allowed.")
        tg.edit(chat_id, msg["message_id"],
                preview + "\n\nOnly the bot's owner can save recipes to Notes.")
        return
    outcome = llm_agent.create_recipe_note(draft)
    if outcome == "created":
        llm_agent.clear_pending_recipe(con, chat_id)
        tg.answer(cb["id"], "Saved.")
        tg.edit(chat_id, msg["message_id"],
                "Saved to Recipes ✓ %s" % draft["title"])
    elif outcome == "duplicate":
        llm_agent.clear_pending_recipe(con, chat_id)
        tg.answer(cb["id"], "Already in Notes.")
        tg.edit(chat_id, msg["message_id"],
                "You already have a recipe called \"%s\" in Notes, so I didn't "
                "save this one. Send the recipe again with a different title if "
                "you want both."
                % draft["title"])
    elif outcome == "no_folder":
        tg.answer(cb["id"], "No Recipes folder.")
        tg.edit(chat_id, msg["message_id"],
                preview + "\n\nThere's no folder called Recipes in Notes. Make "
                "one, then tap Save again.", buttons=_recipe_buttons(draft))
    else:
        tg.answer(cb["id"], "Couldn't reach Notes.")
        tg.edit(chat_id, msg["message_id"],
                preview + "\n\nCouldn't reach Notes just now. Tap Save to try "
                "again.", buttons=_recipe_buttons(draft))


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
        # A removed member keeps their data but stops hearing from the bot.
        if not allowed(con, cfg, chat_id):
            continue
        # Someone halfway through onboarding must not get a scheduled nudge on
        # top of the step they are answering.
        if onb.active(con, chat_id):
            continue
        if not due_today(con, chat_id, cfg, now):
            continue
        # Anything past its budget is past its date too, so it is already a
        # line on the nudge card, marked "long gone". It used to get its own
        # message as well, on top of its line in the nudge.
        send_nudge(tg, con, chat_id, today)
        mark_nudged(con, chat_id, today)
        fridge.prune_cards(con, chat_id, today)
    prune_rate_limits()


# --- main ------------------------------------------------------------------

def main():
    _lock = acquire_lock()   # noqa: F841 (held for the life of the process)
    cfg = load_config()
    if not cfg["allowed_chat_ids"]:
        print("! No allowed_chat_ids set in config.json. This bot will "
              "respond to anyone who finds it.")
    tg = Telegram(cfg["token"])
    con = fridge.connect()
    # Files made before the umask above, or by cp, keep their old modes.
    for path in (CONFIG_PATH, fridge.DB_PATH, llm_agent.RECIPE_CACHE_PATH):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    me = tg.call("getMe")
    if not me or not me.get("ok"):
        sys.exit("! Couldn't reach Telegram. Check the token and your connection.")
    cfg["bot_username"] = me["result"]["username"]
    # The display name set in BotFather, so the copy matches the chat header.
    cfg["bot_name"] = me["result"].get("first_name")
    tg.call("setMyCommands", commands=[
        {"command": c, "description": d} for c, d in COMMANDS])
    if owner(cfg):
        # Only the owner's / menu shows these; they do nothing for anyone else.
        tg.call("setMyCommands", scope={"type": "chat", "chat_id": owner(cfg)},
                commands=[{"command": c, "description": d}
                          for c, d in COMMANDS + OWNER_COMMANDS])
    print("Save Your Food running as @%s. Nudging at %02d:%02d. Ctrl-C to stop."
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
                        handle_message(tg, con, upd["message"], cfg)
                    elif "callback_query" in upd:
                        handle_callback(tg, con, upd["callback_query"], cfg)
            sweep(tg, con, cfg)
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception:
            # Through the same redaction as every other log line: a
            # traceback can quote a URL, and the token lives in the URL.
            print(tg._redact(traceback.format_exc()), file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
