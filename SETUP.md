# SCRS Bot — Complete Setup Guide (Beginner Friendly)

This guide walks you through setting up the SCRS Discord bot **from zero**, clicking-by-clicking. No coding knowledge needed — if you can copy and paste, you can do this. Budget about **30–45 minutes** the first time.

> **Already running and just updating the bot?** Skip to [Part 7 — Updating the bot](#part-7--updating-the-bot-later).

---

## What you're building (the big picture)

The bot is a Python program. It doesn't run on your computer — it runs on a free hosting server that stays on 24/7. Four services are involved, all free:

| Service | What it's for | Cost |
|---|---|---|
| **Discord** (Developer Portal) | Where you create the bot's account | Free |
| **Katabump** | The hosting server the bot lives on | Free (must be renewed every 4 days — see Part 6) |
| **Groq** | The AI brain (chat, voice listening, voice speaking) | Free |
| **Cloudflare** | A tiny relay so Groq will talk to the Katabump server (explained in Part 4) | Free |

> ⚠️ **Golden rule:** the bot's **Discord token** and **Groq API key** are passwords. Never post them in Discord, in a screenshot, or in any GitHub file. Anyone who has them controls the bot / the AI account.

---

## Part 1 — Create the Discord bot (the "app")

1. Open <https://discord.com/developers/applications> and log in with the Discord account that should own the bot.
2. Click **New Application** (top right). Name it `SCRS` and click **Create**.
3. In the left sidebar, click **Bot**, then **Add Bot** → **Yes, do it!** (newer portals create the bot automatically — if you already see bot settings, skip this).
4. Under the bot's username, click **Reset Token** → **Copy**. This is your **Discord token** — paste it into a note for yourself for now. You'll need it in Part 5. (If you ever lose it, come back here and reset it again — resetting kills the old one.)
5. Still on the **Bot** page, scroll to **Privileged Gateway Intents** and turn **ON** these two switches:
   - ✅ **Server Members Intent**
   - ✅ **Message Content Intent**
   - ❌ Presence Intent stays **OFF**.
   Then click **Save Changes**. ⚠️ If you skip this step, the bot logs in but can't see members or read messages, and half the features silently break.
6. Now invite the bot to the server. In the left sidebar click **OAuth2** → **URL Generator**:
   - Under **Scopes**, tick **`bot`** and **`applications.commands`**.
   - A **Bot Permissions** box appears — tick **Administrator**. (This server runs the bot as admin so role-gated features always work; the bot still checks people's roles for every command.)
   - Copy the long URL at the very bottom of the page.
7. Paste that URL into your browser, choose the **Sunshine Coast Roleplay** server, click **Authorize**. The bot now appears in the member list (offline — it comes alive in Part 5).

✅ **Checkpoint:** the bot is in the server's member list, and you have the token saved.

---

## Part 2 — Get a Groq API key (the AI brain)

1. Open <https://console.groq.com> and sign up / log in.
2. In the left sidebar, click **API Keys** → **Create API Key**. Name it anything (e.g. `SCRS bot`).
3. **Copy the key immediately** — Groq only shows it once. It starts with `gsk_`. Save it with your Discord token.
4. **One-time extra step — accept the voice model's terms.** The bot's speaking voice (a model called Orpheus) refuses to work until you accept its terms once:
   - Open <https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english>
   - Type any word in the text box and press the **generate/play** button.
   - A terms window pops up — click **Accept**. (Nothing pops up when the page first loads; it only appears when you actually run the model.)
   - If nothing pops up, check for a thin banner at the top of the page, and try with your ad-blocker paused.

✅ **Checkpoint:** you have a key starting with `gsk_`, and you've accepted the Orpheus terms.

---

## Part 3 — Set up the Katabump server (the bot's home)

1. Open <https://dashboard.katabump.com> and **log in with Discord**.
2. Create a server: choose the **free Python** plan. Name it `SCRS`.
3. Open the server and click **Access server** — this opens the control panel. The panel is where you manage files and start/stop the bot. (The panel has its *own* login shown on that Access screen — identifier + password. Save those in your password manager.)
4. In the panel, open **Files**. You'll upload these files from this GitHub repo (Part 5 explains the `.env` file, which you create here and only here):
   - `bot.py` ← the whole bot, one file
   - `requirements.txt` ← the list of Python packages it needs
   - *(Optional, for reference only: `README.md`, `SETUP.md`, `groq-relay-worker.js`, `.env.example`, `.gitignore`, and an empty `data/` folder.)*
   
   **How to get the files from GitHub:** open the repo → green **Code** button → **Download ZIP** → unzip on your computer. Then drag the files into the panel's Files page.
5. Check the **Startup** page: the startup command should be `python /home/container/bot.py`. It's normally set already for Python servers; don't change anything else there.

Don't press Start yet — the bot needs its `.env` file first (Part 5).

✅ **Checkpoint:** the Katabump server exists and `bot.py` + `requirements.txt` are uploaded.

---

## Part 4 — The Cloudflare relay (needed, or the AI won't answer)

**Why this exists (30-second version):** Groq blocks requests that come from datacenter computers — including Katabump's — with a `403 Access denied` error, before it even looks at your key. Cloudflare Workers are not blocked, so we park a 30-line "mailman" program on Cloudflare: the bot sends its AI requests to the mailman, the mailman hands them to Groq, and hands the answers back. The mailman never holds your Groq key — it just forwards the envelope.

1. Open <https://dash.cloudflare.com> and sign up / log in (free plan is fine).
2. Go to **Workers & Pages** → **Create** → **Worker**. Name it exactly `scrs-groq-relay` and click **Deploy**. (The first time, Cloudflare also asks you to pick a **subdomain** — remember it; your worker's address will be `scrs-groq-relay.<your-subdomain>.workers.dev`. For this server it's `hamza7860100`.)
3. Open the worker → **Edit code**. You'll see a small template program (`worker.js`) that says "Hello World".
   - Click into `worker.js`, press **Ctrl+A** to select all, delete it, and paste in the entire contents of **`groq-relay-worker.js`** from this repo.
   - Click **Deploy** (top right). ⚠️ Editing without Deploying changes nothing — if the worker still says "Hello World" later, this step is why.
   - If the file seems **locked**: you're looking at a read-only copy of an old deployment. Go back to the worker's main page and use its **Edit code** button. Still locked? Delete the worker (Settings → Delete) and redo steps 2–3, pasting the code *before* the first Deploy.
4. Still in the worker: **Settings** → **Variables and Secrets** → **Add** a **Secret**:
   - Name: `RELAY_KEY`
   - Value: invent a password, e.g. `scrs-relay-731`. **Type it by hand** (pasting can smuggle in an invisible trailing space, which caused real debugging pain here). If the page shows a **Deploy** button after saving, click it — secrets only count once deployed.
5. **Test it:** open `https://scrs-groq-relay.<your-subdomain>.workers.dev` in your browser.
   - "Hello World!" → the code from step 3 isn't live yet. Redo step 3 and remember **Deploy**.
   - "Unauthorized" → ✅ perfect. That message means the relay is up and correctly refusing strangers (your browser doesn't know the password; the bot will).

✅ **Checkpoint:** visiting the worker URL says **Unauthorized**.

---

## Part 5 — The `.env` file and first launch

The `.env` file is a plain text file where the bot keeps its secrets and settings. It lives **only on Katabump** — never upload it to GitHub (the repo's `.gitignore` blocks it on purpose).

1. In the Katabump panel **Files** page, click **New File**, name it exactly `.env`, and paste this in, replacing the three placeholder values:

```env
DISCORD_TOKEN=paste-your-discord-token-here
BOT_PREFIX=-
GUILD_ID=1515858046822252684
GROQ_API_KEY=paste-your-groq-key-here
GROQ_BASE_URL=https://scrs-groq-relay.hamza7860100.workers.dev/openai/v1
GROQ_RELAY_KEY=type-the-same-password-as-the-workers-RELAY_KEY
```

2. ⚠️ **The bracket trap:** write the values *bare*. No `< >` around them, no quotes, no spaces. `<scrs-relay-731>` is a **different, wrong** value — those brackets in examples are just placeholders. `GROQ_RELAY_KEY` must be **character-for-character identical** to the `RELAY_KEY` secret on the Worker, or the relay answers `401 Unauthorized`.
3. Save the file.
4. Press **Start** (or **Restart**) on the console page. Give it a minute. The console should show the bot logging in, and in Discord the bot's status flips to **Online**. It also syncs its slash commands to the server on every start — wait ~a minute before testing `/` commands.

### What each `.env` line means

| Line | Meaning | Required? |
|---|---|---|
| `DISCORD_TOKEN` | The bot's Discord password (Part 1, step 4) | ✅ |
| `BOT_PREFIX` | Legacy text prefix; the bot is slash-command based, leave it as `-` | ✅ |
| `GUILD_ID` | The SCRS server's ID — don't change | ✅ |
| `GROQ_API_KEY` | The AI key from Part 2 (`gsk_...`) | ✅ for any AI feature |
| `GROQ_BASE_URL` | Sends AI traffic through your relay (Part 4) | ✅ on Katabump |
| `GROQ_RELAY_KEY` | The shared password with the relay (Part 4, step 4) | ✅ if using the relay |

### Optional settings (safe to ignore — the defaults are the live server values)

| Setting | What it changes |
|---|---|
| `ASSISTANT_CHANNEL_ID` | The channel where the chatbot talks and takes action commands (default `1566062426871304292`) |
| `NINE_ONE_ONE_REQUEST_CHANNEL_ID` | Where civilians may place `/911` calls (default `1564722104274784297`) |
| `NINE_ONE_ONE_POST_CHANNEL_ID` | Where 911 calls are posted + pinged (default `1566086271875424329`) |
| `BOT_LOGS_CHANNEL_ID` | The #bot-logs audit channel (default `1565320716130455562`) |
| `GROQ_LLM_MODEL`, `GROQ_STT_MODEL`, `GROQ_TTS_MODEL`, `GROQ_TTS_VOICE` | Override the AI models / voice (defaults documented in `.env.example`) |

✅ **Checkpoint:** bot is **Online** in Discord.

---

## Part 6 — Check everything works (5 minutes)

1. **`/ping`** in any channel → the bot replies (it's alive).
2. **`/sysinfo`** (High Rank) → the cheat sheet for the whole setup:
   - **FFmpeg / libopus / PyNaCl** all ✅ = voice can work on this host.
   - **Groq API** ✅ reachable (HTTP 200) = the relay + key chain is correct. If it shows ❌ with a number, jump to Troubleshooting — the number tells you which link broke.
3. **Assistant channel:** type a normal message in the assistant channel → the bot chats back. Then (as High Rank) try `infract me for testing` → it should offer **Confirm / Cancel** buttons.
4. **911:** run `/911` *in the request channel* → the call should appear in the dispatch channel with a role ping.
5. **Voice:** join the RTO voice channel, run `/voicejoin`, and say a command out loud. It should repeat what it's about to do and wait for you to say "confirm".

### ⏰ The one chore: Katabump renewal

Free Katabump servers **expire every 4 days**. Renewal is free (dashboard → server → **Renew** → confirm), but if you forget, the bot goes offline until you renew and restart it. The renewal button only unlocks in the last ~day before expiry. Put a repeating reminder on your phone — future-you says thanks.

---

## Part 7 — Updating the bot later

New versions only ever change `bot.py` (and rarely `requirements.txt`):

1. Download the new `bot.py` from this repo (or grab it from the chat where it was sent).
2. Katabump panel → **Files** → upload it over the old one (replace). **Never delete your `.env` or the `data/` folder** — `.env` holds your secrets and `data/` holds all the infractions/strikes/cars/warrants records.
3. **Restart** the server. Done. If `requirements.txt` also changed, restart twice — the first start installs the new packages.

---

## Troubleshooting — every error we actually hit, decoded

The bot prints AI errors in the Katabump console starting with `[SCRS]`. Find yours:

| What you see | What it means | Fix |
|---|---|---|
| `Groq chat error 403: Access denied. Please check your network settings.` | Groq is blocking Katabump's IP address itself (not your key — it fires even for fake keys). | Do **Part 4** (the relay) and make sure `GROQ_BASE_URL` + `GROQ_RELAY_KEY` are in `.env`, then restart. |
| `Groq chat failed: ... text/plain ...` or the worker URL says **Hello World!** | The Cloudflare Worker is still running its starter template. | Part 4, step 3: replace the **contents** of `worker.js`, then **Deploy**. |
| `Groq chat error 401: Unauthorized` (short, plain text) | The relay got the request, but the passwords don't match. | Make `GROQ_RELAY_KEY` (`.env`) and `RELAY_KEY` (Worker secret) **identical**: retype both **by hand**, no brackets/quotes/trailing spaces, redeploy the Worker if it asks, restart the bot. |
| `Groq chat error 401: {"error":{"message":"Invalid API Key"...}}` | You reached Groq, but the **API key itself** is wrong/stale. | Copy a fresh key from console.groq.com → API Keys into `GROQ_API_KEY`. Restart. |
| `Groq TTS error 400: ... requires terms acceptance` | The voice model (Orpheus) terms were never accepted. | Part 2, step 4: open the playground link, type a word, press generate, **Accept**. No restart needed. |
| Voice works but sounds choppy/sloppy | Katabump's free plan caps the server at **25% CPU**, and the server is in France while Discord voice is US — both rough up live audio. Known hosting limit, not a setup mistake. | Nothing to fix in settings; it improves on a paid/US host. |
| Bot is **offline** in Discord | Katabump server expired or stopped. | Renew (Part 6) and **Start** it. Check the console for errors if it won't stay up. |
| Slash commands missing | Commands sync on startup; a fresh restart takes ~a minute. Also, missing intents (Part 1, step 5) cause weird half-working behavior. | Restart, wait a minute, re-check the intents are ON. |
| Assistant channel: "⚠️ The assistant isn't switched on yet" | `GROQ_API_KEY` is missing from `.env`. | Add it (Part 5) and restart. |
| `/911` says calls can only be placed in a channel | You're in the wrong channel — by design. | Use `/911` in the request channel (`1564722104274784297`). The call posts to the dispatch channel automatically. |

---

## Who to ask

Stuck after the table? Copy the exact `[SCRS] ...` line from the Katabump console — it always names the broken link in the chain (bot → relay → Groq), which is 90% of the diagnosis.
