# Installing Save Your Food

Save Your Food (this repo, `fridge-loop`) is a Telegram bot that tracks what is in
your fridge and nudges you before food goes off. This guide installs the Telegram
client, which is the version almost everyone wants: it runs on any computer with
Python, needs no Mac and installs nothing beyond Python itself.

**The goal is one thing: the person can send a photo of their next grocery receipt
and the bot logs their food.** Everything else can come later.

**This guide is written so an AI agent can follow it from start to finish** with no
other knowledge of the project. Every step says who does it:

- **🤖 Agent:** run it yourself, check the result, then move on.
- **👤 You:** the agent cannot do this. It must stop, tell the person exactly what to
  do using the words given, and wait until they say it is done.

If you are a person following this alone, do every step yourself.

---

## Rules for agents

Read these before step 1. They are not optional.

1. **Never ask for the bot token in chat, and never read, print or log it.** The
   token is a password to the bot. The person pastes it into a file on their own
   computer (step 4). You check that it is there with the command given, which
   prints only `OK` or what is wrong, never the token.
2. **The same goes for an OpenRouter API key**, if they turn on AI mode (step 9).
3. **Stop at every 👤 step.** Say what to do, then wait. Do not guess at what they did.
4. **Check every step with its check command** before the next one. If a check fails,
   use the table at the end. If it is not covered there, stop and show the person the
   exact error.
5. **Run commands from the folder each step names.** Every command here assumes it.

---

## Step 1 · Check what is installed 🤖 Agent

    python3 --version
    git --version

**Pass:** both print a version. It was built and tested on Python 3.14; any recent
Python 3 should work.

**If `python3` is missing:** stop and tell the person:

> "Save Your Food needs Python 3. Install it from https://www.python.org/downloads/
> (on a Mac you can also run `brew install python`), then tell me when it's done."

Also note the operating system (`uname -s` prints `Darwin` on a Mac). The bot runs
anywhere, but two optional parts are Mac only: starting it automatically (step 8)
and saving recipes to Apple Notes.

## Step 2 · Get the code 🤖 Agent

    git clone https://github.com/miguelalfredooo/fridge-loop.git
    cd fridge-loop/clients/telegram

Every later step runs from `fridge-loop/clients/telegram` unless it says otherwise.

**Pass:** `ls` shows `bot.py` and `config.example.json`.

## Step 3 · Prove the logic works 🤖 Agent

    python3 test_logic.py; echo "exit=$?"

**Pass:** the last line is `exit=0`. Lines starting with `!` are failures the tests
cause on purpose, and are expected. No token or network is needed for this step.

## Step 4 · Make the bot in Telegram 👤 You

The agent cannot do this: it happens inside the person's Telegram app. Say:

> "Now we'll create your bot in Telegram. This takes about a minute.
>
> 1. Open Telegram and search for **@BotFather** (the one with the blue check).
> 2. Send it `/newbot`.
> 3. It asks for a name. Anything works, for example `My Fridge`.
> 4. It asks for a username ending in `bot`, for example `myfridge_2026_bot`. Try
>    another if it's taken.
> 5. It replies with a **token** that looks like `8123456789:AAF...`.
>
> **Don't paste the token here.** Treat it like a password. Keep that message open;
> you'll paste it into a file in the next step. Tell me when you have it."

Wait for them to confirm.

## Step 5 · Put the token in the config file 🤖 Agent, then 👤 You

**🤖 Agent:** create the config file and lock it so only this account can read it:

    cp config.example.json config.json
    chmod 600 config.json

**👤 You:** on a Mac, run `open -e config.json` for them so it opens in TextEdit.
On other systems, tell them the full path to the file (`pwd` prints the folder).
Then say:

> "A file called `config.json` is open. Find `PUT_YOUR_BOTFATHER_TOKEN_HERE` on the
> second line and replace it with your token, keeping the quote marks around it.
> Save the file and close it, then tell me."

**🤖 Agent check:** this prints `OK`, or what is wrong. It never prints the token.

    python3 -c "import json,re;t=json.load(open('config.json')).get('token','');print('OK' if re.fullmatch(r'\d{6,12}:[A-Za-z0-9_-]{30,}',t) else ('still the placeholder' if 'PUT_YOUR' in t else 'does not look like a BotFather token'))"

If it is not `OK`, ask them to check the line again: the whole token, quote marks
kept, no spaces.

**No file to edit?** (A cloud machine holding the token as a secret.) Set the
`TELEGRAM_BOT_TOKEN` environment variable instead. A real token in `config.json`
still wins over it.

## Step 6 · Lock the bot to the person 👤 You, then 🤖 Agent

Without this, anyone who finds the bot can use it. Say:

> "Let's make the bot answer only you. In Telegram, search for **@userinfobot**, send
> it any message, and tell me the number it shows as your **Id**."

A chat id is not a secret, so they can tell you. **🤖 Agent:** write it into the
config, replacing `123456789` with their number:

    python3 -c "import json;p='config.json';c=json.load(open(p));c['allowed_chat_ids']=[123456789];json.dump(c,open(p,'w'),indent=2)"

**Check:**

    python3 -c "import json;print(json.load(open('config.json'))['allowed_chat_ids'])"

The first id in the list is the **owner**. Only the owner can invite people, see
costs and load a starting fridge.

## Step 7 · Turn on photo reading (recommended) 👤 You decide

**The easiest way to start is a photo of your next grocery receipt**, and reading a
photo needs AI mode. Without it the bot still works, but you type your food in.
Ask:

> "The easiest way to use this is to send a photo of your grocery receipt after you
> shop. To read photos, the bot needs an AI model. Two ways:
>
> - **OpenRouter (recommended):** a website that gives the bot access to an AI model.
>   You pay per message; a receipt costs well under a cent. You'll need to create an
>   account and add a few dollars of credit.
> - **Ollama:** free and runs on your own computer, but needs a fairly powerful one
>   (about 8 GB of free memory).
>
> Or skip it for now and type your food in instead. Which would you like?"

**This always uses the person's own account.** Each install keeps its own keys in
its own `config.json`, so nothing goes through whoever wrote this bot, or anyone
else's account. Say so if they ask.

**Claude or ChatGPT, their choice.** Through OpenRouter one key reaches both, so they
pick whichever they prefer. Tell them:

> "A ChatGPT Plus or Claude Pro subscription doesn't cover this: those are for the
> chat apps, not for other programs. You need your own API access, which is billed
> separately and costs cents. OpenRouter gives you that for both Claude and ChatGPT
> with one account."

**If OpenRouter (👤 You, then 🤖 Agent).** Say:

> "Go to https://openrouter.ai, sign up, add a few dollars of credit, then open
> https://openrouter.ai/keys and create a key. It starts with `sk-or-`. **Don't
> paste it here.** I'll open the config file; replace
> `PUT_YOUR_OPENROUTER_KEY_HERE` with it, keeping the quote marks, then save and tell
> me."

Open the file for them (`open -e config.json` on a Mac). Then set AI mode on, without
touching the key:

    python3 -c "import json;p='config.json';c=json.load(open(p));c['llm_mode']=True;c['llm_provider']='openrouter';json.dump(c,open(p,'w'),indent=2)"

**Check** (prints `OK` or what is wrong, never the key):

    python3 -c "import json;k=json.load(open('config.json')).get('openrouter_api_key','');print('OK' if k.startswith('sk-or-') and len(k)>20 else ('still the placeholder' if 'PUT_YOUR' in k else 'does not look like an OpenRouter key'))"

**Which model:** ask "Claude or ChatGPT?" and set `llm_model` to match. Both read
photos:

| They want | `llm_model` |
|---|---|
| Claude (the default) | `anthropic/claude-haiku-4.5` |
| ChatGPT | `openai/gpt-4o-mini` |

    python3 -c "import json;p='config.json';c=json.load(open(p));c['llm_model']='anthropic/claude-haiku-4.5';json.dump(c,open(p,'w'),indent=2)"

Swap in the ChatGPT model id if that's their choice. Any other model works if its
page at https://openrouter.ai/models lists **image** as an input; a text-only model
silently ignores photos.

**If Ollama (👤 You, then 🤖 Agent).** They install Ollama from https://ollama.com
and open it once. Then you run:

    ollama pull llama3.2-vision
    python3 -c "import json;p='config.json';c=json.load(open(p));c['llm_mode']=True;c['llm_provider']='ollama';json.dump(c,open(p,'w'),indent=2)"

**If they skip:** change nothing. They can do this step any time later; restart the
bot afterwards.

The bot refuses to start in AI mode with OpenRouter and no key, or with an empty
`allowed_chat_ids` (step 6), rather than spending money for anyone who finds it.

## Step 8 · Start the bot 🤖 Agent

Start it as a background process; it keeps running until stopped:

    python3 bot.py

**Pass:** within a few seconds it prints one line:
`Fridge Loop running as @<botname>. Nudging at 16:30. Ctrl-C to stop.`

Then say:

> "Your bot is running. In Telegram, open your bot (search for the username you
> picked) and send `/start`. It asks you a few short questions; tell me what it
> says."

If they get no reply, use the troubleshooting table below.

**Important:** the bot only works while this process runs. If the terminal closes or
the computer sleeps, it stops. Step 9 fixes that on a Mac.

## Step 9 · Keep it running (Mac only, recommended) 🤖 Agent, then 👤 You

Skip this on anything other than a Mac, and tell the person the bot runs only while
`python3 bot.py` is running.

**🤖 Agent:** stop the bot from step 8, then install it as a service that starts at
login and restarts itself if it crashes:

    cd service
    ./install.sh
    ./status.sh

**Pass:** `status.sh` reports it running. `install.sh` is safe to run more than once,
and is also how to restart the bot after a config change.

**👤 You:** two Mac settings the agent cannot change. Say:

> "Two settings so the bot survives a restart or a power cut:
>
> 1. **System Settings → Users & Groups → Automatic login:** turn it on for your
>    account. Otherwise the bot stays off after a restart until you log in.
> 2. **System Settings → Energy:** turn on **Start up automatically after a power
>    failure**.
>
> Tell me when both are done."

Logs are in `~/Library/Logs/fridge-loop/`. To remove the service: `./uninstall.sh`
(your `config.json` and data stay).

## Done

Tell the person:

> "Save Your Food is set up. **Your first step is simple: next time you go grocery
> shopping, send the bot a photo of your receipt.** That's it for now.
> GETTING-STARTED.md has the rest, whenever you want it."

---

## If something goes wrong

| What you see | Cause | Who fixes it, and how |
|---|---|---|
| `! No config.json found` | Step 5 skipped | 🤖 `cp config.example.json config.json` |
| `! config.json has no real token in it yet` | Placeholder still there | 👤 Repeat step 5's paste |
| `Couldn't reach Telegram`, or `telegram getMe failed: 401` | Token wrong or incomplete | 👤 Copy the token again from @BotFather, paste it again |
| Running, but no reply in Telegram | Their chat id isn't in `allowed_chat_ids` (it ignores chats not on the list, on purpose) | 👤 Check the number with @userinfobot. 🤖 Fix the list, restart |
| Warning that the bot is open to anyone | `allowed_chat_ids` empty | Do step 6 |
| Refuses to start in AI mode | No OpenRouter key, or empty `allowed_chat_ids` | Step 7, or step 6 |
| No reminder at the time they picked | The bot wasn't running then, or the Mac slept | Step 9 (Mac). Elsewhere, keep `python3 bot.py` running. Each person picks their time during setup (`/setup` to change it); `nudge_hour` / `nudge_minute` in `config.json` is only the default |
| `./install.sh: No python3 on PATH` | Python not visible to the service | 🤖 `which python3`; 👤 if empty, reinstall Python (step 1) |
| A photo gets `I can't read photos yet` | AI mode is off | Step 7 |
| Anything else | | 🤖 Run `./service/status.sh` (Mac service) or read the terminal output, then show the person the exact error |

## What it keeps, and where

Everything stays on the computer running the bot: `fridge.db` (created on first run)
and `config.json`, both readable only by that account. Nothing is synced anywhere.
In AI mode, messages also go to OpenRouter, or stay on the computer with Ollama. The
bot explains this itself during setup, and `/privacy` shows it again. `/deleteme`
erases everything it holds about whoever sends it.

For everything else, including invites and the full command list, see
`clients/telegram/README.md`.
