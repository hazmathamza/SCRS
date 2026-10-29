# SCRS — Sunshine Coast Roleplay Server Bot

Custom Discord bot for the **Sunshine Coast Roleplay Server (SCRS)** — a Roblox / SWFL roleplay community.

**v2:** every command is a **slash (/) command**. Commands are synced to the SCRS guild on startup, so they appear in Discord's `/` picker as soon as you type `/`. Usage is gated by the server's real roles (**High Rank**, **Staff Team**, **Civilian**); Administrators bypass the gates so admins can always test.

## Commands

| Command | Role needed | What it does |
|---|---|---|
| `/say <message> [channel]` | High Rank | Speak as the bot, in this channel or a chosen one. |
| `/infraction <user> <reason> [proof]` | High Rank | Records an infraction, adds the next **Infraction 1 → 2 → 3** role, DMs the player, logs to **#punishment-logs**. |
| `/uninfraction <user> [reason]` | High Rank | Removes the player's most recent infraction and fixes their Infraction role (drops back a level, or removes it at zero). Logged to #punishment-logs. |
| `/punish <user> <reason> [proof]` | High Rank | Staff strike: applies **Staff Strike 1 → 2 → 3**, DMs them, logs to #punishment-logs. Strike 3 flags a Staff Blacklist review. |
| `/staffpromote <user> <role> [reason]` | High Rank | Gives the member the role and posts a **Promotion** announcement in **#staff-adjustments**. |
| `/staffdemote <user> <role> [reason]` | High Rank | Removes the role and posts a **Demotion** announcement in **#staff-adjustments**. |
| `/startup [notes]` | Staff Team | **Session Startup** embed (with join button) in #startup, pinging Civilian. |
| `/ea [notes]` | Staff Team | **Early Access** session embed in #early-access. |
| `/release [notes]` | Staff Team | **Session Released** embed in #startup, pinging Civilian. |
| `/setup [join info]` | Staff Team | Step-by-step how-to-join embed. |
| `/warrant <user> <reason>` | Staff Team | Puts an **active warrant** on the user (shows on their profile), DMs them, logs to #punishment-logs. |
| `/ticket <user> <reason> <penal code> <amount>` | Staff Team | Issues a **ticket/citation** to a user: Reason / Penal Code / Amount ($). Stored on their profile, DMs them. *(This is a citation, not a support ticket — the server uses Tickety for support tickets.)* |
| `/profile [user]` | Civilian | Profile with a **dropdown**: Overview / Tickets / Registered Cars / Warrants, plus registration (Verified/Bloxlink), roles, infractions and strikes. |
| `/registercar <car name> <color> <plate>` | Civilian | Registers a car to you. Plates are unique server-wide. |
| `/unregistercar <plate>` | Civilian | Removes your car with that plate. |
| `/specialrpreq <roleplay> <details> [when]` | Staff Team | Requests a **special roleplay** — the type is picked from a **dropdown** (bank robbery, hostage situation, prison break, etc.; edit `SPECIAL_RP_TYPES` in `bot.py` to change the list). The request posts to **#special-rp-request** pinging **@Management once**, with **Accept / Deny** buttons (Management / High Rank only). The requesting staff member gets a **DM with the result** either way. |
| `/911 <location> <situation>` | Civilian | Posts a **911 call** in #911 requesting Sheriff, Police and Fire, pinging Emergency Services; units can claim it with the **Responding** button. |
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
2. Upload the new `bot.py` (and `requirements.txt` — unchanged), or upload the zip and extract.
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

Everything persists in `data/store.json`: infractions, strikes, citations (tickets), registered cars, warrants. Delete it (while the bot is stopped) to reset counters/records.
