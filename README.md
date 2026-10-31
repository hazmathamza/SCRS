# SCRS — Sunshine Coast Roleplay Server Bot

Custom Discord bot for the **Sunshine Coast Roleplay Server (SCRS)** — a Roblox / SWFL roleplay community.

**v2:** every command is a **slash (/) command**. Commands are synced to the SCRS guild on startup, so they appear in Discord's `/` picker as soon as you type `/`. Usage is gated by the server's real roles (**High Rank**, **Staff Team**, **Civilian**); Administrators bypass the gates so admins can always test.

## Commands

| Command | Role needed | What it does |
|---|---|---|
| `/say <message> [channel]` | High Rank | Speak as the bot, in this channel or a chosen one. |
| `/infraction <user> <reason> [proof]` | High Rank | Records an infraction, adds the next **Infraction 1 → 2 → 3** role, DMs the player, logs to **#punishment-logs**. |
| `/uninfraction <user> [reason]` | High Rank | Removes the player's most recent infraction and fixes their Infraction role (drops back a level, or removes it at zero). Logged to #punishment-logs. |
| `/staffappeal <user> [reason]` | High Rank | Removes the staff member's most recent strike after a successful appeal, fixing their Staff Strike role level. Logged to #punishment-logs and DM'd. |
| `/punish <user> <reason> [proof]` | High Rank | Staff strike: applies **Staff Strike 1 → 2 → 3**, DMs them, logs to #punishment-logs. Strike 3 flags a Staff Blacklist review. |
| `/staffpromote <user> <role> [reason]` | High Rank | Gives the member the role and posts a **Promotion** announcement in **#staff-adjustments**. |
| `/staffdemote <user> <role> [reason]` | High Rank | Removes the role and posts a **Demotion** announcement in **#staff-adjustments**. |
| `/startup [notes] [link]` | Staff Team | **Session Startup** embed in #startup, pinging Civilian. The host can pass a **join link** — the embed then has a **🎮 Join Session** link button (also on `/ea` and `/release`). |
| `/sessionend [notes] [cleanup]` | Staff Team | Posts a **🔴 Session Ended** embed in #startup and (unless cleanup is turned off) deletes the bot's session posts in #startup / #early-access / #911 — always keeping the **first-ever message in #startup**. |
| `/ea [notes]` | Staff Team | **Early Access** session embed in #early-access. |
| `/release [notes]` | Staff Team | **Session Released** embed in #startup, pinging Civilian. |
| `/setup [join info]` | Staff Team | Step-by-step how-to-join embed. |
| `/warrant <user> <reason>` | Staff Team | Puts an **active warrant** on the user (shows on their profile), DMs them, logs to #punishment-logs. |
| `/ticket <user> <reason> <penal code> <amount>` | Staff Team | Issues a **ticket/citation** to a user: Reason / Penal Code / Amount ($). Stored on their profile, DMs them. *(This is a citation, not a support ticket — the server uses Tickety for support tickets.)* |
| `/arrest <suspect> [jail time] [notes]` | Law Enforcement | Opens a private **paginated charge picker** over the server's **official Florida penal code book — all 161 charges** from the SCRS Penal Codes sheet (codes like `(1)13`, Florida classes from Infraction to Capital, fines, jail in **seconds**). Officers add up to 20 charges across pages; charges stack and total jail **caps at 900s**, and the most serious charge leads the booking (per the sheet's Sentencing Guide). Jail time is officer-selected in seconds (blank = book total). Posts a public arrest record showing every charge with its classification and statute, and **DMs it to the suspect**. Saved on the suspect's profile (Arrests tab). |
| `/cite <suspect> [notes]` | Law Enforcement | Same penal-code charge picker as /arrest, but issues a **citation**: total fine, no jail. Counts with the user's citations/tickets on their profile, and DMs them the breakdown. |
| *(assistant channel)*, `/ask <question>` | Everyone | **Groq chatbot.** Talk to the bot in the assistant channel (ID `1566062426871304292`, override with `ASSISTANT_CHANNEL_ID`) — it chats back with short-term memory of the channel conversation, and it's **penal-code aware**: mention a charge by code or name and it answers from the official book data. `/ask` works anywhere for one-off questions. Needs `GROQ_API_KEY`. |
| `/profile [user]` | Civilian | Profile with a **dropdown**: Overview / Tickets / Registered Cars / Warrants, plus registration (Verified/Bloxlink), roles, infractions and strikes. |
| `/registercar <car name> <color> <plate>` | Civilian | Registers a car to you. Plates are unique server-wide. |
| `/unregistercar <plate>` | Civilian | Removes your car with that plate. |
| `/specialrpreq <roleplay> <details> [when]` | Staff Team | Requests a **special roleplay** — the type is picked from a **dropdown** (bank robbery, hostage situation, prison break, etc.; edit `SPECIAL_RP_TYPES` in `bot.py` to change the list). The request posts to **#special-rp-request** pinging **@Management once**, with **Accept / Deny** buttons (Management / High Rank only). The requesting staff member gets a **DM with the result** either way. |
| `/911 <service> <location> <situation>` | Civilian | Posts a **911 call** in #911. The caller **chooses the service — Police, Sheriff, Fire Department, or All** — and the bot **pings that service's role**. Hooked up to Vaydin's roles (verified Oct 30, 2026): Police → **Sarasota Police Department**, Sheriff → **Sarasota County**, Fire → **Sarasota Fire Department** (exact names first, partial-name match if renamed, Emergency Services fallback if a service role is ever missing). Units can claim the call with the **Responding** button. |
| `/voicejoin [channel]`, `/voiceleave` | High Rank | **Groq voice assistant.** The bot joins your voice channel (or RTO) and listens to High Rank speakers: speech → Whisper transcription → LLM (gpt-oss-120b) tool-calling → for infractions/strikes/tickets/warrants it **speaks back what it's about to do and waits for a spoken "confirm"** before executing; results are posted as embeds, DM'd, and audited in #bot-logs. While a session is active, **911 calls are read aloud** in the channel (dispatch). Needs `GROQ_API_KEY` in `.env` + the voice packages in requirements.txt (PyNaCl, discord-ext-voice-recv, davey). Model IDs are env-overridable (see `.env.example`). |
| `/sysinfo` | High Rank | Host diagnostics: Python/discord.py versions, FFmpeg path, libopus, PyNaCl, voice-ready verdict. |
| `/ping`, `/help` | Anyone | Latency/uptime check and the command list. |

**Command logging:** every slash command used (successful or failed) is logged to **#bot-logs** (channel ID `1565320716130455562`, override with the `BOT_LOGS_CHANNEL_ID` env var) with the user, channel, options and status.

Infraction/punishment logs go to **#punishment-logs** — never #punishment-request. If that channel doesn't exist, the bot creates it under the Staff category on startup (it needs Manage Channels for that; otherwise create the channel manually).

## Developer Portal checklist

1. **Bot → Privileged Gateway Intents:** **Server Members Intent** and **Message Content Intent** ON (verified Oct 28, 2026).
2. The bot's server role must be **above** the `Infraction 1-3` and `Staff Strike 1-3` roles, and above any role used with `/staffpromote` / `/staffdemote`, or Discord will refuse the change.
3. Slash commands are guild-synced on startup (instant). No re-invite is needed when upgrading from v1 if the bot was invited with the `bot` scope; if `/` commands don't appear after a restart, re-invite once with `scope=bot+applications.commands`:

```
https://discord.com/oauth2/authorize?client_id=1564958134886334497&permissions=8&scope=bot%20applications.commands
```

## Updating on Katabump (from v1)

1. Panel → **Files**: delete the old `bot.py` (keep your `.env` and `data/store.json` — v2 reads the same data file and adds the new sections automatically).
2. Upload the new `bot.py` and `requirements.txt` (v3 adds PyNaCl + discord-ext-voice-recv + davey for voice), or upload the zip and extract. For voice, also add `GROQ_API_KEY=...` to your `.env`.
3. **Restart** the server. Console shows slash commands syncing, then `Logged in as SCRS#8394`.
4. In Discord, type `/` — the SCRS commands should be listed.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # paste your token into .env
python bot.py
```

## Data

Everything persists in `data/store.json`: infractions, strikes, citations (tickets), arrests, registered cars, warrants, special RP requests. Delete it (while the bot is stopped) to reset counters/records.
