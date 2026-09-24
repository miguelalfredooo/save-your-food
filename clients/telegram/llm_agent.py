"""LLM-driven conversational mode. Opt-in, off by default.

The regex-based pipeline in bot.py/fridge.py is the whole system when
llm_mode is false in config.json (the default), and this file changes
nothing about it. This module is a separate, self-contained natural-language
front end for people who would rather talk to the bot than learn its command
shape: a message here never reaches is_chatter, correction, parse_list, or
onboarding. It reads and writes the same items/pantry tables fridge.py
defines, through its own tool-calling loop, because the model is meant to
read context a keyword table cannot ("butter chicken (leftovers)", "ate the
spinach") rather than because the schema is different.

Needs an OpenRouter API key in config.json (openrouter_api_key) and costs
money per message, which is why it defaults to off.
"""

import json
import urllib.error
import urllib.request
from datetime import date, timedelta

import fridge
import shelf_life as sl

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOOL_ROUNDS = 4   # a runaway tool-call loop must not hang a chat forever
REQUEST_TIMEOUT = 30

SYSTEM_PROMPT = """You are Fridge Loop: a friend who's good in the kitchen and helps
people use food before it goes bad. You're texting in Telegram.

Today: {today}
Fridge: {fridge_items}
Pantry: {pantry_items}

UNDERSTAND FIRST
Every message is one of: adding food, updating/removing food
("ate the spinach", "tossed the milk"), asking a question,
asking what's in the fridge, or just chatting. Work out which
before calling any tool.
- Never log a question, reaction, or comment as a food item.
- If you can't tell whether something is food, ask.
- Read natural phrasing: "put butter chicken in the fridge as
  leftovers" = add "butter chicken (leftovers)", ~3-4 days.
- Leftovers, opened items and cooked food get short windows;
  sealed items get typical shelf life.

DATES
You estimate expiry from typical shelf life. Store your
confidence in the tool call, never as a label in the reply.
When it matters, say it like a person: "should be good till
about Sunday. Trust your nose past that." If they give a real
date, use it.

PANTRY
Rice, dry lentils, cans, spices go to the pantry quietly. Don't
explain the system unless asked.

HOW YOU TALK
- 1-3 short sentences, like a text from a friend.
- Confirm in passing, not as a receipt: "Got it" beats
  "Tracking 1 thing:".
- Lists only when they ask what's in the fridge.
- Add one useful thing when you can: a quick idea, or a pairing
  with something already in there that's close to expiring.
- Vary your wording. No stock phrases.

Tools: add_items, update_item, remove_item, list_items.
If no tool fits, just reply."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_items",
            "description": "Add one or more food items to tracking. Perishables "
                           "get an estimated date; shelf-stable goods go to the "
                           "pantry with no date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string",
                                         "description": "The food, e.g. \"butter chicken (leftovers)\""},
                                "estimated_days": {"type": "integer",
                                                    "description": "Days from today until it likely turns"},
                                "stated_date": {"type": "boolean",
                                                "description": "True if the user gave a real date rather than you estimating"},
                                "pantry": {"type": "boolean",
                                           "description": "True for shelf-stable goods with no clock: rice, dry lentils, cans, spices"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_item",
            "description": "Close out a tracked item as used, frozen, or tossed, "
                           "or correct its estimated date. Different from "
                           "remove_item: this keeps the item in the record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "state": {"type": "string", "enum": ["used", "frozen", "tossed"]},
                    "estimated_days": {"type": "integer",
                                       "description": "New estimate, if correcting the date instead of closing it out"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item",
            "description": "Delete a tracked item outright, e.g. it was added "
                           "by mistake. Different from update_item, which "
                           "closes an item out and keeps it in the record.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_items",
            "description": "Get the current fridge and pantry contents to "
                           "answer a question about them.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# --- prompt building --------------------------------------------------------

def _fridge_summary(con, chat_id, today):
    items = fridge.open_items(con, chat_id)
    if not items:
        return "empty"
    return "; ".join(
        "%s (%s, %s)" % (i["name"], sl.when(i["use_by_date"], today),
                          "my guess" if i["estimated"] else "your date")
        for i in items
    )


def _pantry_summary(con, chat_id):
    items = fridge.pantry_items(con, chat_id)
    if not items:
        return "empty"
    return ", ".join(i["name"] for i in items)


def build_system_prompt(con, chat_id, today=None):
    today = today or date.today()
    return SYSTEM_PROMPT.format(
        today=today.strftime("%A %B %d"),
        fridge_items=_fridge_summary(con, chat_id, today),
        pantry_items=_pantry_summary(con, chat_id),
    )


# --- tool execution ----------------------------------------------------------
#
# These write to the same items/pantry tables fridge.py defines, but not
# through fridge.add_items(): that function always derives the date from
# shelf_life.py's keyword table, and the whole point of this mode is letting
# the model's own estimate win when it has more context than a keyword table
# can. The risk class (for the disposal-budget clock) still comes from
# shelf_life.py, since that classification is independent of the date guess.

def _find_open_item(con, chat_id, name):
    """Case-insensitive, forgiving match: the model's own words for an item
    rarely match the stored name exactly ("the spinach" vs "spinach")."""
    n = (name or "").lower().strip()
    if not n:
        return None
    items = fridge.open_items(con, chat_id)
    for i in items:
        if i["name"].lower() == n:
            return i
    for i in items:
        if n in i["name"].lower() or i["name"].lower() in n:
            return i
    return None


def exec_add_items(con, chat_id, args, today):
    added, went_to_pantry = [], []
    for it in args.get("items") or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        if it.get("pantry") or sl.not_tracked(name)[0]:
            fridge.remember(con, chat_id, name, "stable", today)
            went_to_pantry.append(name)
            continue
        days = it.get("estimated_days")
        use_by = (today + timedelta(days=int(days))) if days is not None \
            else sl.use_by(name, today)[0]
        estimated = not it.get("stated_date")
        risk = sl.lookup(name)[1]
        existing = _find_open_item(con, chat_id, name)
        if existing:
            con.execute("UPDATE items SET use_by=?, estimated=? WHERE id=?",
                        (use_by.isoformat(), 1 if estimated else 0, existing["id"]))
        else:
            con.execute(
                "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
                " VALUES (?,?,?,?,?,?, 'open')",
                (chat_id, name, use_by.isoformat(), risk, 1 if estimated else 0,
                 today.isoformat()))
        added.append({"name": name, "use_by": use_by.isoformat()})
    con.commit()
    return {"added": added, "pantry": went_to_pantry}


def exec_update_item(con, chat_id, args, today):
    item = _find_open_item(con, chat_id, args.get("name"))
    if not item:
        return {"error": "no open item matching '%s'" % args.get("name")}
    state = args.get("state")
    if state in ("used", "frozen", "tossed"):
        fridge.close_item(con, chat_id, item["id"], state)
        return {"ok": True, "name": item["name"], "state": state}
    days = args.get("estimated_days")
    if days is not None:
        use_by = today + timedelta(days=int(days))
        con.execute("UPDATE items SET use_by=?, estimated=1 WHERE id=?",
                    (use_by.isoformat(), item["id"]))
        con.commit()
        return {"ok": True, "name": item["name"], "use_by": use_by.isoformat()}
    return {"error": "nothing to update"}


def exec_remove_item(con, chat_id, args):
    item = _find_open_item(con, chat_id, args.get("name"))
    if not item:
        return {"error": "no open item matching '%s'" % args.get("name")}
    con.execute("DELETE FROM items WHERE id=?", (item["id"],))
    con.commit()
    return {"ok": True, "name": item["name"]}


def exec_list_items(con, chat_id, today):
    items = fridge.open_items(con, chat_id)
    pantry = fridge.pantry_items(con, chat_id)
    return {
        "fridge": [{"name": i["name"], "use_by": i["use_by"],
                    "estimated": bool(i["estimated"])} for i in items],
        "pantry": [i["name"] for i in pantry],
    }


TOOL_EXECUTORS = {
    "add_items": lambda con, chat_id, args, today: exec_add_items(con, chat_id, args, today),
    "update_item": lambda con, chat_id, args, today: exec_update_item(con, chat_id, args, today),
    "remove_item": lambda con, chat_id, args, today: exec_remove_item(con, chat_id, args),
    "list_items": lambda con, chat_id, args, today: exec_list_items(con, chat_id, today),
}


# --- the model call ----------------------------------------------------------

def call_openrouter(api_key, model, messages, tools, timeout=REQUEST_TIMEOUT):
    body = json.dumps({"model": model, "messages": messages, "tools": tools}).encode()
    req = urllib.request.Request(
        API_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % api_key,
        })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def run_agent(con, chat_id, text, cfg, today=None, caller=None):
    """caller lets tests substitute a fake model instead of the real API, the
    same shape FakeTG substitutes for the real Telegram class."""
    today = today or date.today()
    call = caller or (lambda messages: call_openrouter(
        cfg["openrouter_api_key"], cfg["llm_model"], messages, TOOLS))

    messages = [
        {"role": "system", "content": build_system_prompt(con, chat_id, today)},
        {"role": "user", "content": text},
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = call(messages)
        except Exception as e:
            return "Having trouble thinking right now. Try again in a bit. (%s)" % e
        choice = resp["choices"][0]["message"]
        tool_calls = choice.get("tool_calls")
        if not tool_calls:
            return choice.get("content") or "..."
        messages.append(choice)
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (ValueError, TypeError):
                args = {}
            executor = TOOL_EXECUTORS.get(name)
            result = executor(con, chat_id, args, today) if executor \
                else {"error": "unknown tool %r" % name}
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })
    return "Got a bit tangled up there. Try again?"
