# SCRS — Sunshine Coast Roleplay Server Bot

Custom Discord bot for the **Sunshine Coast Roleplay Server (SCRS)** — a Roblox / SWFL roleplay community.

Built to Vaydin's spec: prefix commands (`-`), gated by the server's real roles (**High Rank**, **Staff Team**, **Civilian**), and wired to the server's real channels (`#startup`, `#early-access`, `#911`, `#ticket-logs`, the **Tickets** category, and more). Administrators bypass role gates so admins can always test.

## Commands

| Command | Role needed | What it does |
|---|---|---|
| `-say [#channel] <message>` | High Rank | Speak as the bot, in this channel or a chosen one. Your command message is deleted. |
| `-startup [notes]` | Staff Team | Posts a **Session Startup** embed (with a join button) in `#startup`, pinging Civilian. |
| `-ea [notes]` | Staff Team | Posts an **Early Access** session embed in `#early-access`, pinging Early Access. |
| `-release [notes]` | Staff Team | Posts a **Session Released** embed — the session is open to everyone. |
| `-setup [join info]` | Staff Team | Posts the step-by-step **how to join / set up** embed. |
| `-infraction @user Reason: … Proof: …` | High Rank | Records an infraction and adds the next **Infraction 1 → 2 → 3** role. DMs the player and logs to HR. Infraction 3 flags escalation. |
| `-punish @user Reason: … Proof: …` | High Rank | Records a staff strike and applies **Staff Strike 1 → 2 → 3** (replacing the lower strike role). DMs the staff member and logs it. Strike 3 flags a Staff Blacklist review. |
| `-profile [@user]` | Civilian | Shows profile: avatar, IDs, account + server join dates, registration (Verified / Bloxlink), roles, tickets opened, infractions and strikes. |
| `-ticket [@user] [reason]` | Civilian | Creates a private `ticket-<name>-<n>` channel under the Tickets category for you (or a mentioned user), visible to staff, with a **Close Ticket** button. Counted on your profile and logged to `#ticket-logs`. |
| `-911 <location> \| <situation>` | Civilian | Posts a **911 call** in `#911` requesting Sheriff, Police and Fire, pinging Emergency Services. Units can press **Responding** to claim the call. |
| `-ping` | Anyone | Latency, uptime and server check. |
| `-help` | Anyone | The full command list, in Discord. |
| `-close` | Ticket owner / Staff | Closes the ticket channel you're in. |

Accepted formats for `-infraction` / `-punish`: `Reason: … Proof: …`, or `reason | proof`, or just a reason.

## Before it works — Developer Portal checklist

In the [Discord Developer Portal](https://discord.com/developers/applications) for this bot:

1. **Bot → Privileged Gateway Intents:** turn ON **Server Members Intent** and **Message Content Intent**.
2. The bot's role in the server (Discord → Server Settings → Roles) must be **above** the `Infraction 1-3` and `Staff Strike 1-3` roles, or it can't assign them.
3. Invite / re-invite URL (Administrator is the simplest for setup; scope it down later if you want):

```
https://discord.com/oauth2/authorize?client_id=1564958134886334497&permissions=8&scope=bot
```

## Run it on Katabump

1. In the Katabump panel, create a **Discord bot (Python)** server.
2. Upload these files (or pull from this repo) so `bot.py` is in the server root.
3. In **Startup / environment variables**, set:
   - `DISCORD_TOKEN` = your bot token *(never put this in GitHub or in `bot.py`)*
   - Startup file / command: `bot.py` (Katabump Python egg runs `python bot.py` — it installs `requirements.txt` automatically)
4. Press **Start**. Console should print: `Logged in as SCRS#8394` and `Serving guild: Sunshine Coast Roleplay Server`.
5. Test in **#bot-testing** (Staff category): `-ping`, then each command above.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # paste your token into .env
python bot.py
```

## Data

Tickets, infractions and strikes persist in `data/store.json` (created automatically, git-ignored). Delete it to reset counters.

## Notes / limits

- `-profile` "registration" reflects the server's **Verified** role (granted via Bloxlink in `#verify`) — the bot can't query Bloxlink directly.
- Buttons (join / responding / close) work while the bot is running; after a restart, buttons on very old messages may need a fresh post.
- Command names are case-insensitive: `-Infraction`, `-INFRACTION` and `-infraction` all work. The 911 command is typed exactly as `-911`.
