"""
SCRS — Sunshine Coast Roleplay Server Discord Bot  (v2, slash commands)
========================================================================
Built for the SCRS server (Sunshine Coast Roleplay Server, Roblox / SWFL RP).

ALL commands are slash (/) commands, registered (synced) to the SCRS guild
on startup so they show up in Discord's "/" picker as soon as you type /.

Commands & roles:
    /ping            Anyone     Latency / uptime check
    /help            Anyone     Command list
    /say             High Rank  Speak as the bot (optional channel)
    /infraction      High Rank  Issue an infraction (Infraction 1-3 roles)
    /uninfraction    High Rank  Remove a user's latest infraction
    /punish          High Rank  Staff strike (Staff Strike 1-3 roles)
    /startup         Staff Team Session startup announcement (#startup)
    /ea              Staff Team Early Access announcement (#early-access)
    /release         Staff Team Session released announcement
    /setup           Staff Team How-to-join / setup embed
    /staffpromote    High Rank  Give a staff member a role — announced in
                                #staff-adjustments
    /staffdemote     High Rank  Remove a role from a staff member —
                                announced in #staff-adjustments
    /warrant         Staff Team Put a warrant on a user
    /ticket          Staff Team Issue a ticket/citation to a user:
                                Reason / Penal Code / Amount
    /profile         Civilian   Profile with a dropdown: Overview /
                                Tickets / Registered Cars / Warrants
    /registercar     Civilian   Register a car: Car Name / Color / Plate
    /unregistercar   Civilian   Remove one of your cars by plate
    /911             Civilian   911 call to Sheriff / Police / Fire (#911)

Infraction & punishment records are logged to #punishment-logs
(the bot creates that channel under the Staff category if it's missing).
They are NEVER posted to #punishment-request.

Token comes from the DISCORD_TOKEN environment variable / .env — never
hard-coded, never committed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = int(os.getenv("GUILD_ID", "1515858046822252684"))
LOG_CHANNEL_NAME = "punishment-logs"
ADJUSTMENTS_CHANNEL_NAME = "staff-adjustments"
SPECIAL_RP_CHANNEL_NAME = "special-rp-request"
BOT_LOGS_CHANNEL_ID = int(os.getenv("BOT_LOGS_CHANNEL_ID", "1565320716130455562"))

# Special roleplay types — chosen from the dropdown in /specialrpreq.
# Edit this list to change what shows in the dropdown.
SPECIAL_RP_TYPES = [
    "Bank Robbery",
    "Jewelry Store Robbery",
    "Store Robbery",
    "Hostage Situation",
    "High-Speed Pursuit",
    "Street Race",
    "Prison Break",
    "SWAT Raid",
    "Major Structure Fire",
    "Major Vehicle Crash / Mass Casualty",
    "Aircraft Emergency",
    "Other (explain in details)",
]

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "store.json"

HIGH_RANK_ROLES = {
    "Owner",
    "Co Owner",
    "Founders",
    "Bot Maker",
    "High Rank",
    "Management",
    "Staff Manager",
    "Discord Administration",
    "Sigma Bot Crafter",
}
STAFF_ROLES = HIGH_RANK_ROLES | {
    "Staff Team",
    "Senior Staff",
    "Junior Staff",
    "Server Staff",
    "Staff In Training",
}
CIVILIAN_ROLES = STAFF_ROLES | {"Civilian", "Verified"}

COLOUR_MAIN = discord.Colour.from_rgb(255, 170, 0)
COLOUR_OK = discord.Colour.from_rgb(46, 204, 113)
COLOUR_ALERT = discord.Colour.from_rgb(231, 76, 60)
COLOUR_INFO = discord.Colour.from_rgb(52, 152, 219)
COLOUR_EA = discord.Colour.from_rgb(155, 89, 182)
COLOUR_STAFF = discord.Colour.from_rgb(241, 196, 15)

START_TIME = time.time()

# --------------------------------------------------------------------------- #
# Persistent store (JSON)
# --------------------------------------------------------------------------- #

STORE_DEFAULTS = {
    "infractions": {},   # user_id -> [ {by, reason, proof, level, at} ]
    "strikes": {},       # user_id -> [ {by, reason, proof, level, at} ]
    "citations": {},     # user_id -> [ {by, reason, penal_code, amount, at} ]
    "arrests": {},       # user_id -> [ {by, charges: [codes], fine, jail, top_class, notes, at} ]
    "cars": {},          # user_id -> [ {car_name, color, plate, at} ]
    "warrants": {},      # user_id -> [ {by, reason, at, active} ]
    "special_rp_requests": [],  # [ {requester, type, details, status, at, decided_by} ]
    "tickets": {},       # legacy v1 support-ticket counters (kept, unused)
    "ticket_counter": 0,
}


def load_store() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = {**STORE_DEFAULTS, **data}
    return merged


def save_store(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


store = load_store()

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def has_any_role(member: discord.Member, names: set[str]) -> bool:
    return any(role.name in names for role in member.roles)


def passes(member: discord.Member, group: set[str]) -> bool:
    """Admins bypass role gates so server admins can always use/test commands."""
    if member.guild_permissions and member.guild_permissions.administrator:
        return True
    return has_any_role(member, group)


def find_role(guild: discord.Guild, *names: str) -> discord.Role | None:
    for name in names:
        role = discord.utils.get(guild.roles, name=name)
        if role:
            return role
    return None


def find_channel(guild: discord.Guild, *names: str) -> discord.TextChannel | None:
    lowered = [n.lower() for n in names]
    for channel in guild.text_channels:
        if channel.name.lower() in lowered:
            return channel
    return None


def base_embed(title: str, colour: discord.Colour, description: str = "") -> discord.Embed:
    embed = discord.Embed(
        title=title, description=description, colour=colour, timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Sunshine Coast Roleplay Server • SCRS")
    return embed


async def get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """#punishment-logs — created under the Staff category if missing."""
    channel = find_channel(guild, LOG_CHANNEL_NAME)
    if channel:
        return channel
    category = None
    for cat in guild.categories:
        if "staff" in cat.name.lower():
            category = cat
            break
    try:
        return await guild.create_text_channel(
            name=LOG_CHANNEL_NAME,
            category=category,
            topic="Infraction & punishment logs for SCRS (posted by the SCRS bot)",
            reason="SCRS bot: punishment-logs channel required by spec",
        )
    except discord.HTTPException:
        return None


async def log_punishment(guild: discord.Guild, embed: discord.Embed) -> None:
    """Log to #punishment-logs ONLY — never #punishment-request."""
    channel = await get_log_channel(guild)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def safe_dm(member: discord.Member, embed: discord.Embed) -> None:
    try:
        await member.send(embed=embed)
    except discord.HTTPException:
        pass


def _format_options(interaction: discord.Interaction) -> str:
    """Flatten a slash command's options into 'name: value' lines for logs."""
    lines: list[str] = []

    def walk(options: list[dict], prefix: str = "") -> None:
        for opt in options or []:
            if opt.get("type") in (1, 2):  # subcommand / subcommand group
                walk(opt.get("options", []), prefix)
            else:
                value = opt.get("value", "—")
                if isinstance(value, str) and len(value) > 120:
                    value = value[:117] + "…"
                lines.append(f"{opt.get('name', '?')}: {value}")

    try:
        walk((interaction.data or {}).get("options", []))
    except Exception:
        return ""
    return "\n".join(lines)


async def send_bot_log(
    interaction: discord.Interaction, status: str, detail: str = ""
) -> None:
    """Log a command use to #bot-logs. Never raises — logging must not break commands."""
    try:
        if not interaction.guild:
            return
        channel = interaction.guild.get_channel(BOT_LOGS_CHANNEL_ID)
        if channel is None:
            channel = await interaction.client.fetch_channel(BOT_LOGS_CHANNEL_ID)
        if channel is None:
            return
        command = interaction.command
        name = f"/{command.qualified_name}" if command else "/unknown"
        embed = base_embed(f"📝 Command Used — {name}", COLOUR_INFO if status == "✅" else COLOUR_ALERT)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        if interaction.channel:
            embed.add_field(name="Channel", value=f"#{getattr(interaction.channel, 'name', 'unknown')}", inline=True)
        options_text = _format_options(interaction)
        if options_text:
            embed.add_field(name="Options", value=options_text[:1024], inline=False)
        if detail:
            embed.add_field(name="Detail", value=detail[:1024], inline=False)
        await channel.send(embed=embed)
    except Exception as exc:  # logging is best-effort only
        print(f"[SCRS] bot-log failed: {exc}", file=sys.stderr)


# NOTE: command-use logging hooks in via the `on_app_command_completion`
# BOT EVENT (defined below) — discord.py's CommandTree dispatches that event;
# there is no CommandTree method to override for it.


# --------------------------------------------------------------------------- #
# Role checks for slash commands
# --------------------------------------------------------------------------- #


def check_group(group: set[str], label: str):
    def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if isinstance(member, discord.Member) and interaction.guild and passes(member, group):
            return True
        raise app_commands.CheckFailure(label)

    return app_commands.check(predicate)


high_rank_only = lambda: check_group(HIGH_RANK_ROLES, "High Rank")
staff_only = lambda: check_group(STAFF_ROLES, "Staff Team")
civilian_only = lambda: check_group(CIVILIAN_ROLES, "Civilian")

# Law-enforcement gate for /arrest and /cite: the emergency-service roles,
# plus Staff and High Rank (admins bypass as usual).
LEO_ROLES = {
    "Emergency Services",
    "Sarasota Police Department",
    "Sarasota County",
    "Sarasota Fire Department",
    "Police",
    "Police Department",
    "Sheriff",
    "Sheriff's Office",
    "Fire Department",
}
LEO_GATE = HIGH_RANK_ROLES | STAFF_ROLES | LEO_ROLES
leo_only = lambda: check_group(LEO_GATE, "Law Enforcement")


# --------------------------------------------------------------------------- #
# Interactive views
# --------------------------------------------------------------------------- #


class SessionView(discord.ui.View):
    def __init__(self, link: str = "") -> None:
        super().__init__(timeout=None)
        self.attendees: set[int] = set()
        if link:
            # URL button — clicking it opens the host's session join link.
            self.add_item(
                discord.ui.Button(label="🎮 Join Session", style=discord.ButtonStyle.link, url=link)
            )

    @discord.ui.button(label="✅ I'm joining", style=discord.ButtonStyle.success, custom_id="scrs_session_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id in self.attendees:
            await interaction.response.send_message("You're already on the join list for this session.", ephemeral=True)
            return
        self.attendees.add(interaction.user.id)
        button.label = f"✅ I'm joining ({len(self.attendees)})"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("You're on the list — see you in session! 🚗", ephemeral=True)


class NineOneOneView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.claimed_by: str | None = None

    @discord.ui.button(label="🚨 Responding", style=discord.ButtonStyle.danger, custom_id="scrs_911_respond")
    async def respond(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.claimed_by:
            await interaction.response.send_message(
                f"This call is already being handled by {self.claimed_by}.", ephemeral=True
            )
            return
        self.claimed_by = interaction.user.mention
        button.label = f"🚨 Responding: {interaction.user.display_name}"
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{interaction.user.mention} is responding to this 911 call.")


# --------------------------------------------------------------------------- #
# Profile (with dropdown: Overview / Tickets / Cars / Warrants)
# --------------------------------------------------------------------------- #


def active_warrants(user_id: int) -> list[dict]:
    return [w for w in store["warrants"].get(str(user_id), []) if w.get("active", True)]


def profile_embed(member: discord.Member, section: str = "overview") -> discord.Embed:
    uid = str(member.id)
    infractions = store["infractions"].get(uid, [])
    strikes = store["strikes"].get(uid, [])
    citations = store["citations"].get(uid, [])
    arrests = store.get("arrests", {}).get(uid, [])
    cars = store["cars"].get(uid, [])
    warrants = active_warrants(member.id)

    titles = {
        "overview": f"👤 Profile — {member.display_name}",
        "tickets": f"🎫 Tickets — {member.display_name}",
        "cars": f"🚗 Registered Cars — {member.display_name}",
        "warrants": f"📜 Warrants — {member.display_name}",
        "arrests": f"🚔 Arrests — {member.display_name}",
    }
    embed = base_embed(titles.get(section, titles["overview"]), COLOUR_MAIN)
    embed.set_thumbnail(url=member.display_avatar.url)

    if section == "tickets":
        if not citations:
            embed.description = "No tickets on record. ✅"
        else:
            lines = []
            total = 0
            for i, c in enumerate(reversed(citations), 1):
                total += int(c.get("amount", 0))
                when = str(c.get("at", ""))[:10]
                lines.append(
                    f"**#{len(citations) - i + 1}** — {when} • **${int(c.get('amount', 0)):,}**\n"
                    f"Reason: {c.get('reason', '—')} • Penal Code: {c.get('penal_code', '—')}"
                )
            embed.description = "\n\n".join(lines[:10])
            embed.add_field(name="Total fines", value=f"${total:,}", inline=True)
            embed.add_field(name="Tickets", value=str(len(citations)), inline=True)
    elif section == "cars":
        if not cars:
            embed.description = "No cars registered. Use `/registercar` to add one."
        else:
            lines = [
                f"**{c.get('car_name', '—')}** — {c.get('color', '—')} • Plate: `{c.get('plate', '—')}`"
                for c in cars
            ]
            embed.description = "\n".join(lines[:15])
            embed.add_field(name="Cars registered", value=str(len(cars)), inline=True)
    elif section == "arrests":
        if not arrests:
            embed.description = "No arrests on record. ✅"
        else:
            lines = []
            for i, a in enumerate(reversed(arrests), 1):
                when = str(a.get("at", ""))[:10]
                codes = ", ".join(a.get("charges", []))
                lines.append(
                    f"**#{len(arrests) - i + 1}** — {when} • {a.get('top_class', '—')} • "
                    f"Fine ${int(a.get('fine', 0)):,} • Jail {int(a.get('jail', 0))} min\n"
                    f"Charges: {codes}"
                )
            embed.description = "\n\n".join(lines[:10])
            embed.add_field(name="Total arrests", value=str(len(arrests)), inline=True)
    elif section == "warrants":
        if not warrants:
            embed.description = "No active warrants. ✅"
        else:
            lines = [f"• {w.get('reason', '—')} ({str(w.get('at', ''))[:10]})" for w in warrants]
            embed.description = "\n".join(lines[:10])
            embed.add_field(name="Active warrants", value=str(len(warrants)), inline=True)
    else:
        verified = has_any_role(member, {"Verified"})
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        embed.add_field(name="User", value=f"{member.mention}\n`{member}`", inline=True)
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.add_field(name="Top Role", value=member.top_role.mention if member.top_role else "—", inline=True)
        embed.add_field(name="Discord Registered", value=member.created_at.strftime("%b %d, %Y"), inline=True)
        embed.add_field(
            name="Joined SCRS",
            value=member.joined_at.strftime("%b %d, %Y") if member.joined_at else "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Registration",
            value="✅ Verified (Bloxlink)" if verified else "❌ Not verified — see #verify",
            inline=True,
        )
        embed.add_field(name="Tickets", value=str(len(citations)), inline=True)
        embed.add_field(name="Arrests", value=str(len(arrests)), inline=True)
        embed.add_field(name="Registered Cars", value=str(len(cars)), inline=True)
        embed.add_field(name="Active Warrants", value=str(len(warrants)), inline=True)
        embed.add_field(name="Infractions", value=str(len(infractions)), inline=True)
        embed.add_field(name="Staff Strikes", value=str(len(strikes)), inline=True)
        embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
        embed.set_footer(text="Use the dropdown below for Tickets / Cars / Warrants • SCRS")
    return embed


class ProfileView(discord.ui.View):
    def __init__(self, member: discord.Member) -> None:
        super().__init__(timeout=300)
        self.member = member

    @discord.ui.select(
        placeholder="View: Overview / Tickets / Cars / Warrants…",
        custom_id="scrs_profile_select",
        options=[
            discord.SelectOption(label="Overview", value="overview", emoji="👤"),
            discord.SelectOption(label="Tickets", value="tickets", emoji="🎫"),
            discord.SelectOption(label="Registered Cars", value="cars", emoji="🚗"),
            discord.SelectOption(label="Warrants", value="warrants", emoji="📜"),
            discord.SelectOption(label="Arrests", value="arrests", emoji="🚔"),
        ],
    )
    async def select_section(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.edit_message(
            embed=profile_embed(self.member, select.values[0]), view=self
        )


# --------------------------------------------------------------------------- #
# Bot
# --------------------------------------------------------------------------- #

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


class SCRSBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Guild-scoped sync: slash commands appear in the / picker instantly
        # for this server (global sync can take up to an hour).
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[SCRS] Slash commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            print("[SCRS] Slash commands synced globally")


bot = SCRSBot(command_prefix="!", intents=intents)  # prefix unused; slash only


@bot.event
async def on_ready() -> None:
    print(f"[SCRS] Logged in as {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        print(f"[SCRS] Serving guild: {guild.name} ({guild.id}) — {guild.member_count} members")
        await get_log_channel(guild)  # make sure #punishment-logs exists
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Sunshine Coast RP | /help")
    )


@bot.event
async def on_app_command_completion(
    interaction: discord.Interaction, command: app_commands.Command
) -> None:
    """Fired by discord.py after every successful slash command — log it to #bot-logs."""
    await send_bot_log(interaction, "✅ Completed")


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    await send_bot_log(interaction, "❌ Failed", detail=f"{type(error).__name__}: {error}"[:300])
    if isinstance(error, app_commands.CheckFailure):
        needed = str(error) or "required"
        embed = base_embed(
            "⛔ You don't have permission for that",
            COLOUR_ALERT,
            f"This command needs the **{needed}** role (or Administrator).",
        )
    elif isinstance(error, app_commands.MissingPermissions):
        embed = base_embed("⛔ Missing permissions", COLOUR_ALERT, "You don't have permission to run that.")
    else:
        print(f"[SCRS] App command error: {error}", file=sys.stderr)
        embed = base_embed("❌ Something went wrong", COLOUR_ALERT, "That command hit an error — check the bot console.")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


# --------------------------------------------------------------------------- #
# Utility slash commands
# --------------------------------------------------------------------------- #


@bot.tree.command(name="ping", description="Check the SCRS bot is alive")
async def ping(interaction: discord.Interaction) -> None:
    uptime = int(time.time() - START_TIME)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    embed = base_embed("🏓 Pong!", COLOUR_OK)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
    embed.add_field(name="Server", value=interaction.guild.name if interaction.guild else "DM", inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sysinfo", description="Diagnostics: Python / FFmpeg / Opus / PyNaCl (voice feature readiness)")
@high_rank_only()
async def sysinfo(interaction: discord.Interaction) -> None:
    """Reports whether this host can support voice playback (for the 911
    voice-dispatch feature): FFmpeg binary, libopus, and PyNaCl."""
    import platform
    import shutil

    ffmpeg_path = shutil.which("ffmpeg")
    opus_loaded = discord.opus.is_loaded()
    opus_detail = "loaded"
    if not opus_loaded:
        opus_detail = "not loaded"
        for lib in ("libopus.so.0", "libopus.so", "libopus", "opus"):
            try:
                discord.opus.load_opus(lib)
                if discord.opus.is_loaded():
                    opus_loaded = True
                    opus_detail = f"loaded via {lib}"
                    break
            except Exception:
                continue
    try:
        import nacl  # noqa: F401

        nacl_ok = True
    except Exception:
        nacl_ok = False

    voice_ready = bool(ffmpeg_path) and opus_loaded and nacl_ok
    embed = base_embed("🖥️ System Info — SCRS Bot Host", COLOUR_INFO)
    embed.add_field(name="Python", value=platform.python_version(), inline=True)
    embed.add_field(name="discord.py", value=discord.__version__, inline=True)
    embed.add_field(name="FFmpeg", value=ffmpeg_path or "❌ NOT FOUND", inline=True)
    embed.add_field(name="libopus", value=("✅ " if opus_loaded else "❌ ") + opus_detail, inline=True)
    embed.add_field(name="PyNaCl (voice)", value="✅ installed" if nacl_ok else "❌ missing", inline=True)
    embed.add_field(
        name="Voice dispatch ready?",
        value="✅ YES — FFmpeg + opus + PyNaCl all present" if voice_ready else "❌ NO — see missing items above",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="help", description="List all SCRS bot commands")
async def help_command(interaction: discord.Interaction) -> None:
    embed = base_embed(
        "📖 SCRS Bot — Commands",
        COLOUR_MAIN,
        "All commands are **slash commands** — type `/` and pick from the list.",
    )
    embed.add_field(
        name="🔊 High Rank",
        value=(
            "`/say` — speak as the bot\n"
            "`/infraction` / `/uninfraction` — give / remove a player infraction (Infraction 1–3)\n"
            "`/punish` — staff strike (Staff Strike 1–3)\n"
            "`/staffappeal` — remove a staff strike after a successful appeal\n"
            "`/staffpromote` / `/staffdemote` — give / remove a staff role (announced in #staff-adjustments)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛠️ Staff Team",
        value=(
            "`/startup` — session startup in #startup\n"
            "`/ea` — Early Access session in #early-access\n"
            "`/release` — release the session to everyone\n"
            "`/setup` — how to join / set up for the session\n"
            "`/sessionend` — end the session + clean up the session channels\n"
            "`/warrant` — put a warrant on a user\n"
            "`/ticket` — issue a ticket: Reason / Penal Code / Amount\n"
            "`/arrest` / `/cite` — pick charges from the penal code (up to 15 at once) [Law Enforcement]\n"
            "`/specialrpreq` — request a special roleplay (dropdown) — Management accepts/denies in #special-rp-request"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 Civilian (everyone)",
        value=(
            "`/profile` — profile with dropdown: Tickets / Registered Cars / Warrants\n"
            "`/registercar` — register a car (Car Name / Color / Plate)\n"
            "`/unregistercar` — remove your car by plate\n"
            "`/911` — call Police, Sheriff or Fire (you choose — it pings their role)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎙️ Voice (High Rank)",
        value=(
            "`/voicejoin` — bot joins your voice channel (or RTO): speak commands, it confirms out loud before acting\n"
            "`/voiceleave` — stop the voice assistant\n"
            "While active, 911 calls are read aloud in the channel (dispatch)."
        ),
        inline=False,
    )
    embed.add_field(name="⚙️ Utility", value="`/ping` — check the bot • `/sysinfo` — host diagnostics [High Rank]", inline=False)
    await interaction.response.send_message(embed=embed)


# --------------------------------------------------------------------------- #
# High Rank
# --------------------------------------------------------------------------- #


@bot.tree.command(name="say", description="Speak as the bot in this channel (or a chosen channel)")
@high_rank_only()
@app_commands.describe(message="What the bot should say", channel="Channel to speak in (default: this one)")
async def say(
    interaction: discord.Interaction, message: str, channel: discord.TextChannel | None = None
) -> None:
    target = channel or interaction.channel
    await target.send(message)
    await interaction.response.send_message(f"✅ Spoken in {target.mention}", ephemeral=True)


@bot.tree.command(name="infraction", description="Give a player an infraction (adds Infraction 1–3 role)")
@high_rank_only()
@app_commands.describe(user="Player receiving the infraction", reason="Why they're receiving it", proof="Proof (link or description)")
async def infraction(
    interaction: discord.Interaction, user: discord.Member, reason: str, proof: str = "Not provided"
) -> None:
    records = store["infractions"].setdefault(str(user.id), [])
    level = min(len(records) + 1, 3)

    role_note = "No Infraction roles were found in this server."
    role = find_role(interaction.guild, f"Infraction {level}")
    if role:
        try:
            if role not in user.roles:
                await user.add_roles(role, reason=f"Infraction {level} by {interaction.user}: {reason}")
            role_note = f"Added role: **Infraction {level}**"
        except discord.Forbidden:
            role_note = f"⚠️ Couldn't add **Infraction {level}** — move the SCRS bot role above it and try again."

    records.append(
        {
            "by": interaction.user.id,
            "reason": reason,
            "proof": proof,
            "level": level,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["infractions"][str(user.id)] = records
    save_store(store)

    embed = base_embed("⚠️ Infraction Issued", COLOUR_ALERT)
    embed.add_field(name="Player", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Infraction", value=f"Infraction {level} of 3", inline=True)
    embed.add_field(name="Issued by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Proof", value=proof, inline=False)
    embed.add_field(name="Role", value=role_note, inline=False)
    if level >= 3:
        embed.add_field(name="🚨 Escalation", value="This player is at **Infraction 3** — refer to High Rank for further action.", inline=False)
    await interaction.response.send_message(embed=embed)
    await log_punishment(interaction.guild, embed)  # -> #punishment-logs, NOT punishment-request
    await safe_dm(user, embed)


@bot.tree.command(name="uninfraction", description="Remove a player's most recent infraction")
@high_rank_only()
@app_commands.describe(user="Player to un-infraction", reason="Why the infraction is being removed")
async def uninfraction(
    interaction: discord.Interaction, user: discord.Member, reason: str = "No reason given"
) -> None:
    records = store["infractions"].get(str(user.id), [])
    if not records:
        await interaction.response.send_message(
            embed=base_embed("ℹ️ Nothing to remove", COLOUR_INFO, f"{user.mention} has no infractions on record."),
            ephemeral=True,
        )
        return

    removed = records.pop()
    store["infractions"][str(user.id)] = records
    save_store(store)
    old_level = int(removed.get("level", len(records) + 1))
    new_level = len(records)

    notes = []
    guild = interaction.guild
    old_role = find_role(guild, f"Infraction {old_level}")
    if old_role and old_role in user.roles:
        try:
            await user.remove_roles(old_role, reason=f"Infraction removed by {interaction.user}: {reason}")
            notes.append(f"Removed role: **Infraction {old_level}**")
        except discord.Forbidden:
            notes.append(f"⚠️ Couldn't remove **Infraction {old_level}** (bot role too low).")
    if new_level > 0:
        lower_role = find_role(guild, f"Infraction {new_level}")
        if lower_role and lower_role not in user.roles:
            try:
                await user.add_roles(lower_role, reason="Infraction level lowered")
                notes.append(f"Now at: **Infraction {new_level}**")
            except discord.Forbidden:
                pass

    embed = base_embed("✅ Infraction Removed", COLOUR_OK)
    embed.add_field(name="Player", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Infractions remaining", value=str(new_level), inline=True)
    embed.add_field(name="Removed by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    if notes:
        embed.add_field(name="Roles", value="\n".join(notes), inline=False)
    await interaction.response.send_message(embed=embed)
    await log_punishment(guild, embed)
    await safe_dm(user, embed)


@bot.tree.command(name="punish", description="Put a staff strike on a user (Staff Strike 1–3 roles)")
@high_rank_only()
@app_commands.describe(user="Staff member receiving the strike", reason="Why they're receiving it", proof="Proof (link or description)")
async def punish(
    interaction: discord.Interaction, user: discord.Member, reason: str, proof: str = "Not provided"
) -> None:
    records = store["strikes"].setdefault(str(user.id), [])
    level = min(len(records) + 1, 3)

    role_note = "No Staff Strike roles were found in this server."
    new_role = find_role(interaction.guild, f"Staff Strike {level}")
    if new_role:
        try:
            for old_level in (1, 2, 3):
                old_role = find_role(interaction.guild, f"Staff Strike {old_level}")
                if old_role and old_role in user.roles and old_role != new_role:
                    await user.remove_roles(old_role, reason="Superseded by higher strike")
            if new_role not in user.roles:
                await user.add_roles(new_role, reason=f"Staff Strike {level} by {interaction.user}: {reason}")
            role_note = f"Added role: **Staff Strike {level}**"
        except discord.Forbidden:
            role_note = f"⚠️ Couldn't add **Staff Strike {level}** — move the SCRS bot role above it and try again."

    records.append(
        {
            "by": interaction.user.id,
            "reason": reason,
            "proof": proof,
            "level": level,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["strikes"][str(user.id)] = records
    save_store(store)

    embed = base_embed("🔨 Staff Strike Issued", COLOUR_ALERT)
    embed.add_field(name="Staff Member", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Strike", value=f"Staff Strike {level} of 3", inline=True)
    embed.add_field(name="Issued by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Proof", value=proof, inline=False)
    embed.add_field(name="Role", value=role_note, inline=False)
    if level >= 3:
        embed.add_field(
            name="🚨 Escalation",
            value="This is **Strike 3** — refer to High Rank / Management for a Staff Blacklist review.",
            inline=False,
        )
    await interaction.response.send_message(embed=embed)
    await log_punishment(interaction.guild, embed)
    await safe_dm(user, embed)


@bot.tree.command(name="staffappeal", description="Remove a staff strike after a successful appeal")
@high_rank_only()
@app_commands.describe(user="Staff member whose strike was appealed", reason="Appeal outcome / reason for removal")
async def staffappeal(
    interaction: discord.Interaction, user: discord.Member, reason: str = "Appeal accepted"
) -> None:
    records = store["strikes"].get(str(user.id), [])
    if not records:
        await interaction.response.send_message(
            embed=base_embed("ℹ️ Nothing to remove", COLOUR_INFO, f"{user.mention} has no staff strikes on record."),
            ephemeral=True,
        )
        return

    removed = records.pop()
    store["strikes"][str(user.id)] = records
    save_store(store)
    old_level = int(removed.get("level", len(records) + 1))
    new_level = len(records)

    notes = []
    guild = interaction.guild
    old_role = find_role(guild, f"Staff Strike {old_level}")
    if old_role and old_role in user.roles:
        try:
            await user.remove_roles(old_role, reason=f"Strike appealed by {interaction.user}: {reason}")
            notes.append(f"Removed role: **Staff Strike {old_level}**")
        except discord.Forbidden:
            notes.append(f"⚠️ Couldn't remove **Staff Strike {old_level}** (bot role too low).")
    if new_level > 0:
        lower_role = find_role(guild, f"Staff Strike {new_level}")
        if lower_role and lower_role not in user.roles:
            try:
                await user.add_roles(lower_role, reason="Strike level lowered after appeal")
                notes.append(f"Now at: **Staff Strike {new_level}**")
            except discord.Forbidden:
                pass

    embed = base_embed("✅ Staff Strike Removed (Appeal)", COLOUR_OK)
    embed.add_field(name="Staff Member", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Strikes remaining", value=str(new_level), inline=True)
    embed.add_field(name="Appeal handled by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    if notes:
        embed.add_field(name="Roles", value="\n".join(notes), inline=False)
    await interaction.response.send_message(embed=embed)
    await log_punishment(guild, embed)
    await safe_dm(user, embed)


# --------------------------------------------------------------------------- #
# Staff promotions / demotions — announced in #staff-adjustments
# --------------------------------------------------------------------------- #


async def _announce_adjustment(interaction: discord.Interaction, embed: discord.Embed) -> None:
    channel = find_channel(interaction.guild, ADJUSTMENTS_CHANNEL_NAME)
    if channel:
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Announced in {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed)
        await interaction.followup.send(
            "⚠️ #staff-adjustments channel wasn't found, so the announcement was posted here instead.",
            ephemeral=True,
        )


@bot.tree.command(name="staffpromote", description="Promote a staff member (give them a role) — announced in #staff-adjustments")
@high_rank_only()
@app_commands.describe(user="Staff member being promoted", role="The role to give them", reason="Reason for the promotion")
async def staffpromote(
    interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str = "No reason given"
) -> None:
    if role in user.roles:
        await interaction.response.send_message(f"{user.mention} already has {role.mention}.", ephemeral=True)
        return
    try:
        await user.add_roles(role, reason=f"Promotion by {interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed(
                "❌ Can't give that role",
                COLOUR_ALERT,
                "The SCRS bot's role must be **above** the role being given. Move the bot role up in Server Settings → Roles.",
            ),
            ephemeral=True,
        )
        return
    embed = base_embed("⬆️ Staff Promotion", COLOUR_OK)
    embed.add_field(name="Staff Member", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="New Role", value=role.mention, inline=True)
    embed.add_field(name="Promoted by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await _announce_adjustment(interaction, embed)
    await safe_dm(user, embed)


@bot.tree.command(name="staffdemote", description="Demote a staff member (remove a role) — announced in #staff-adjustments")
@high_rank_only()
@app_commands.describe(user="Staff member being demoted", role="The role to remove from them", reason="Reason for the demotion")
async def staffdemote(
    interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str = "No reason given"
) -> None:
    if role not in user.roles:
        await interaction.response.send_message(f"{user.mention} doesn't have {role.mention}.", ephemeral=True)
        return
    try:
        await user.remove_roles(role, reason=f"Demotion by {interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed(
                "❌ Can't remove that role",
                COLOUR_ALERT,
                "The SCRS bot's role must be **above** the role being removed. Move the bot role up in Server Settings → Roles.",
            ),
            ephemeral=True,
        )
        return
    embed = base_embed("⬇️ Staff Demotion", COLOUR_ALERT)
    embed.add_field(name="Staff Member", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Role Removed", value=role.mention, inline=True)
    embed.add_field(name="Demoted by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await _announce_adjustment(interaction, embed)
    await safe_dm(user, embed)


# --------------------------------------------------------------------------- #
# Staff Team — sessions
# --------------------------------------------------------------------------- #


def _valid_link(link: str) -> bool:
    return not link or link.startswith(("http://", "https://"))


async def _post_session(
    interaction: discord.Interaction,
    target_names: list[str],
    embed: discord.Embed,
    ping_role_names: list[str],
    link: str = "",
) -> None:
    target = find_channel(interaction.guild, *target_names) or interaction.channel
    ping = ""
    for name in ping_role_names:
        role = find_role(interaction.guild, name)
        if role:
            ping = role.mention
            break
    await target.send(content=ping or None, embed=embed, view=SessionView(link))
    await interaction.response.send_message(f"✅ Posted in {target.mention}", ephemeral=True)


@bot.tree.command(name="startup", description="Announce a session startup in #startup")
@staff_only()
@app_commands.describe(notes="Details / join info for the session", link="Session join link (e.g. Roblox private server link) — adds a Join Session button")
async def startup(interaction: discord.Interaction, notes: str = "", link: str = "") -> None:
    if not _valid_link(link):
        await interaction.response.send_message(
            "That link doesn't look right — links must start with `https://`.", ephemeral=True
        )
        return
    embed = base_embed(
        "🟢 Session Startup — SCRS",
        COLOUR_OK,
        "A Sunshine Coast roleplay session is **starting now**! Get set up and join up.",
    )
    embed.add_field(name="Host", value=interaction.user.mention, inline=True)
    embed.add_field(name="Status", value="🟢 Starting", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    embed.add_field(
        name="How to join",
        value=(
            "Click **🎮 Join Session** below to join, and check #information for the session steps."
            if link
            else "Check #information for the join steps, be in uniform / correct vehicle class, and click **I'm joining** below."
        ),
        inline=False,
    )
    await _post_session(interaction, ["startup"], embed, ["Civilian", "Verified"], link=link)


@bot.tree.command(name="ea", description="Announce an Early Access session in #early-access")
@staff_only()
@app_commands.describe(notes="Details / join info for the session", link="Session join link — adds a Join Session button")
async def ea(interaction: discord.Interaction, notes: str = "", link: str = "") -> None:
    if not _valid_link(link):
        await interaction.response.send_message(
            "That link doesn't look right — links must start with `https://`.", ephemeral=True
        )
        return
    embed = base_embed(
        "🟣 Early Access Session — SCRS",
        COLOUR_EA,
        "An **Early Access** session is opening for Early Access members before the public release.",
    )
    embed.add_field(name="Host", value=interaction.user.mention, inline=True)
    embed.add_field(name="Status", value="🟣 Early Access", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    embed.add_field(name="Next step", value="When the session opens to everyone, staff will run `/release`.", inline=False)
    await _post_session(interaction, ["early-access"], embed, ["Early Access", "Civilian"], link=link)


@bot.tree.command(name="release", description="Release the session to the public")
@staff_only()
@app_commands.describe(notes="Details / join info for the session", link="Session join link — adds a Join Session button")
async def release(interaction: discord.Interaction, notes: str = "", link: str = "") -> None:
    if not _valid_link(link):
        await interaction.response.send_message(
            "That link doesn't look right — links must start with `https://`.", ephemeral=True
        )
        return
    embed = base_embed(
        "🔓 Session Released — Open to Everyone",
        COLOUR_INFO,
        "The session is now **released** — all Civilian players may join. Have a great roleplay!",
    )
    embed.add_field(name="Released by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Status", value="🔓 Public", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    await _post_session(interaction, ["startup"], embed, ["Civilian", "Verified"], link=link)


@bot.tree.command(name="setup", description="Post the session setup / how-to-join embed")
@staff_only()
@app_commands.describe(join_info="Join code or join info (optional)")
async def setup_cmd(interaction: discord.Interaction, join_info: str = "") -> None:
    embed = base_embed(
        "🧰 Session Setup — How to Join SCRS",
        COLOUR_STAFF,
        "Follow these steps to get into the session correctly:",
    )
    embed.add_field(name="1️⃣ Join", value=f"Use the join info: **{join_info}**" if join_info else "Use the join info posted in #startup.", inline=False)
    embed.add_field(name="2️⃣ Verify", value="Make sure you're verified (see #verify) so you have the Civilian role.", inline=False)
    embed.add_field(name="3️⃣ Get ready", value="Correct uniform / vehicle for your department or civilian role, and follow #rules at all times.", inline=False)
    embed.add_field(name="4️⃣ Need help?", value="Ask in #support-channel or open a ticket with the server's ticket bot.", inline=False)
    embed.add_field(name="Session Host", value=interaction.user.mention, inline=True)
    await interaction.response.send_message(embed=embed)


# --------------------------------------------------------------------------- #
# Staff Team — warrant & ticket (citation)
# --------------------------------------------------------------------------- #


@bot.tree.command(name="warrant", description="Put a warrant on a user")
@staff_only()
@app_commands.describe(user="User the warrant is for", reason="Reason for the warrant")
async def warrant(interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
    records = store["warrants"].setdefault(str(user.id), [])
    records.append(
        {
            "by": interaction.user.id,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
            "active": True,
        }
    )
    store["warrants"][str(user.id)] = records
    save_store(store)

    embed = base_embed("📜 Warrant Issued", COLOUR_ALERT)
    embed.add_field(name="User", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Issued by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Active warrants", value=str(len(active_warrants(user.id))), inline=True)
    embed.add_field(name="Status", value="🔴 ACTIVE — law enforcement may arrest on sight per server rules.", inline=False)
    await interaction.response.send_message(embed=embed)
    await log_punishment(interaction.guild, embed)
    await safe_dm(user, embed)


@bot.tree.command(name="ticket", description="Issue a ticket (citation) to a user: Reason / Penal Code / Amount")
@staff_only()
@app_commands.describe(user="User receiving the ticket", reason="Reason for the ticket", penal_code="Penal code violated", amount="Fine amount in $")
async def ticket(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str,
    penal_code: str,
    amount: app_commands.Range[int, 0, 1000000],
) -> None:
    records = store["citations"].setdefault(str(user.id), [])
    records.append(
        {
            "by": interaction.user.id,
            "reason": reason,
            "penal_code": penal_code,
            "amount": int(amount),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["citations"][str(user.id)] = records
    save_store(store)

    embed = base_embed("🎫 Ticket Issued", COLOUR_STAFF)
    embed.add_field(name="User", value=f"{user.mention} ({user.display_name})", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Penal Code", value=penal_code, inline=True)
    embed.add_field(name="Amount", value=f"${int(amount):,}", inline=True)
    embed.add_field(name="Issued by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Total tickets", value=str(len(records)), inline=True)
    await interaction.response.send_message(embed=embed)
    await log_punishment(interaction.guild, embed)
    await safe_dm(user, embed)


# --------------------------------------------------------------------------- #
# Penal code book + /arrest + /cite  (requested by ehyugf6, Oct 30 2026)
#
# Officers pick charges from the penal code below — up to 15 at once — and
# the bot works out the classification/severity, total fine and suggested
# jail time from the book. On /arrest the officer can override the jail
# time. The suspect is DM'd the full breakdown. Edit PENAL_CODES to match
# the server's official penal code document.
# --------------------------------------------------------------------------- #

# classification -> severity rank (higher = more severe)
CLASS_RANK = {
    "Infraction": 1,
    "Misdemeanor": 2,
    "Felony": 3,
    "Second-Degree Felony": 4,
    "First-Degree Felony": 5,
}
CLASS_EMOJI = {
    "Infraction": "🟢",
    "Misdemeanor": "🟡",
    "Felony": "🟠",
    "Second-Degree Felony": "🔴",
    "First-Degree Felony": "⚫",
}

# code, title, classification, fine $, suggested jail (minutes)
PENAL_CODES: list[dict] = [
    {"code": "PC-101", "title": "Speeding", "classification": "Infraction", "fine": 150, "jail": 0},
    {"code": "PC-102", "title": "Disorderly Conduct", "classification": "Infraction", "fine": 75, "jail": 0},
    {"code": "PC-103", "title": "Trespassing", "classification": "Infraction", "fine": 100, "jail": 0},
    {"code": "PC-201", "title": "Reckless Driving", "classification": "Misdemeanor", "fine": 300, "jail": 5},
    {"code": "PC-202", "title": "Resisting Arrest", "classification": "Misdemeanor", "fine": 250, "jail": 5},
    {"code": "PC-203", "title": "Assault", "classification": "Misdemeanor", "fine": 400, "jail": 10},
    {"code": "PC-204", "title": "Drug Possession", "classification": "Misdemeanor", "fine": 350, "jail": 10},
    {"code": "PC-205", "title": "Obstruction of Justice", "classification": "Misdemeanor", "fine": 300, "jail": 8},
    {"code": "PC-206", "title": "Vandalism", "classification": "Misdemeanor", "fine": 200, "jail": 5},
    {"code": "PC-301", "title": "Evading a Law Enforcement Officer", "classification": "Felony", "fine": 750, "jail": 15},
    {"code": "PC-302", "title": "Grand Theft Auto", "classification": "Felony", "fine": 800, "jail": 20},
    {"code": "PC-303", "title": "Assault with a Deadly Weapon", "classification": "Felony", "fine": 1000, "jail": 25},
    {"code": "PC-304", "title": "Possession of an Illegal Firearm", "classification": "Felony", "fine": 900, "jail": 20},
    {"code": "PC-305", "title": "Drug Trafficking", "classification": "Felony", "fine": 1800, "jail": 35},
    {"code": "PC-306", "title": "Bribery of an Officer", "classification": "Felony", "fine": 1200, "jail": 20},
    {"code": "PC-401", "title": "Armed Robbery", "classification": "Second-Degree Felony", "fine": 1500, "jail": 30},
    {"code": "PC-402", "title": "Attempted Murder", "classification": "Second-Degree Felony", "fine": 2000, "jail": 40},
    {"code": "PC-403", "title": "Kidnapping", "classification": "Second-Degree Felony", "fine": 2500, "jail": 40},
    {"code": "PC-501", "title": "Bank Robbery", "classification": "First-Degree Felony", "fine": 3000, "jail": 45},
    {"code": "PC-502", "title": "Murder", "classification": "First-Degree Felony", "fine": 5000, "jail": 60},
]
PENAL_BY_CODE = {c["code"]: c for c in PENAL_CODES}


def charge_totals(codes: list[str]) -> tuple[int, int, str]:
    """(total fine, suggested jail minutes, highest classification) for charge codes."""
    fine = sum(PENAL_BY_CODE[c]["fine"] for c in codes)
    jail = sum(PENAL_BY_CODE[c]["jail"] for c in codes)
    top = max((PENAL_BY_CODE[c]["classification"] for c in codes), key=lambda cl: CLASS_RANK[cl])
    return fine, jail, top


def charge_lines(codes: list[str]) -> str:
    lines = []
    for c in codes:
        ch = PENAL_BY_CODE[c]
        emoji = CLASS_EMOJI[ch["classification"]]
        jail = f" • {ch['jail']} min jail" if ch["jail"] else ""
        lines.append(
            f"{emoji} **{ch['code']} — {ch['title']}**\n"
            f"{ch['classification']} • ${ch['fine']:,}{jail}"
        )
    return "\n".join(lines)


class ChargeSelectView(discord.ui.View):
    """Ephemeral charge picker shown to the officer after /arrest or /cite."""

    def __init__(
        self,
        *,
        kind: str,
        officer: discord.Member,
        suspect: discord.Member,
        jail_time: int | None = None,
        notes: str | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.kind = kind  # "arrest" or "cite"
        self.officer = officer
        self.suspect = suspect
        self.jail_time = jail_time
        self.notes = notes
        self.selected: list[str] = []
        select = discord.ui.Select(
            placeholder="Select charges from the penal code (up to 15)…",
            min_values=1,
            max_values=15,
            custom_id="scrs_charge_select",
            options=[
                discord.SelectOption(
                    label=f"{c['code']} — {c['title']}"[:100],
                    value=c["code"],
                    description=f"{c['classification']} • ${c['fine']:,}"[:100],
                    emoji=CLASS_EMOJI[c["classification"]],
                )
                for c in PENAL_CODES
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Only the issuing officer can use this picker.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.selected = list(interaction.data.get("values", []))  # type: ignore[attr-defined]
        fine, jail, top = charge_totals(self.selected)
        await interaction.response.edit_message(
            content=(
                f"**{len(self.selected)} charge(s) selected** — total fine **${fine:,}**, "
                f"suggested jail **{jail} min**, highest classification **{top}**. "
                "Press Confirm to issue."
            ),
            view=self,
        )

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        if not self.selected:
            await interaction.response.send_message("Pick at least one charge first.", ephemeral=True)
            return
        fine, suggested_jail, top = charge_totals(self.selected)
        now = datetime.now(timezone.utc).isoformat()

        if self.kind == "arrest":
            jail_final = self.jail_time if self.jail_time is not None else suggested_jail
            records = store["arrests"].setdefault(str(self.suspect.id), [])
            records.append(
                {
                    "by": self.officer.id,
                    "charges": list(self.selected),
                    "fine": fine,
                    "jail": jail_final,
                    "top_class": top,
                    "notes": self.notes or "",
                    "at": now,
                }
            )
            store["arrests"][str(self.suspect.id)] = records
            save_store(store)

            embed = base_embed("🚔 Arrest Record", COLOUR_ALERT)
            embed.add_field(name="Suspect", value=f"{self.suspect.mention} ({self.suspect.display_name})", inline=False)
            embed.add_field(name="Charges", value=charge_lines(self.selected), inline=False)
            embed.add_field(
                name="⚖️ Classification",
                value=f"Highest severity: **{top}** ({len(self.selected)} charge{'s' if len(self.selected) != 1 else ''})",
                inline=False,
            )
            embed.add_field(name="Total fine", value=f"${fine:,}", inline=True)
            embed.add_field(
                name="Jail time",
                value=f"{jail_final} min" + ("" if self.jail_time is not None else f" (book suggestion: {suggested_jail} min)"),
                inline=True,
            )
            if self.notes:
                embed.add_field(name="Officer notes", value=self.notes, inline=False)
            embed.add_field(name="Arresting officer", value=self.officer.mention, inline=True)
            embed.add_field(name="Total arrests", value=str(len(records)), inline=True)
            embed.set_footer(text="You have the right to appeal this arrest to High Rank. • SCRS")
            title_done = "Arrest posted"
        else:  # cite
            records = store["citations"].setdefault(str(self.suspect.id), [])
            records.append(
                {
                    "by": self.officer.id,
                    "reason": "; ".join(PENAL_BY_CODE[c]["title"] for c in self.selected),
                    "penal_code": ", ".join(self.selected),
                    "charges": list(self.selected),
                    "amount": fine,
                    "top_class": top,
                    "notes": self.notes or "",
                    "at": now,
                }
            )
            store["citations"][str(self.suspect.id)] = records
            save_store(store)

            embed = base_embed("🎫 Citation Issued", COLOUR_STAFF)
            embed.add_field(name="Suspect", value=f"{self.suspect.mention} ({self.suspect.display_name})", inline=False)
            embed.add_field(name="Charges", value=charge_lines(self.selected), inline=False)
            embed.add_field(name="⚖️ Classification", value=f"Highest severity: **{top}**", inline=False)
            embed.add_field(name="Total fine", value=f"${fine:,}", inline=True)
            if self.notes:
                embed.add_field(name="Officer notes", value=self.notes, inline=False)
            embed.add_field(name="Issued by", value=self.officer.mention, inline=True)
            embed.add_field(name="Total citations", value=str(len(records)), inline=True)
            embed.set_footer(text="Pay or appeal this citation per server rules. • SCRS")
            title_done = "Citation posted"

        await interaction.response.edit_message(content=f"✅ {title_done}.", embed=None, view=None)
        if interaction.channel:
            await interaction.channel.send(embed=embed)
        if interaction.guild:
            await log_punishment(interaction.guild, embed)
        await safe_dm(self.suspect, embed)
        self.stop()

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(content="Cancelled — nothing was issued.", embed=None, view=None)
        self.stop()


@bot.tree.command(name="arrest", description="Arrest a suspect: pick charges from the penal code (up to 15 at once)")
@leo_only()
@app_commands.describe(
    suspect="The suspect being arrested",
    jail_time="Jail time in minutes (leave blank to use the penal code's suggested total)",
    notes="Optional officer notes",
)
async def arrest(
    interaction: discord.Interaction,
    suspect: discord.Member,
    jail_time: app_commands.Range[int, 0, 600] | None = None,
    notes: str | None = None,
) -> None:
    view = ChargeSelectView(
        kind="arrest", officer=interaction.user, suspect=suspect, jail_time=jail_time, notes=notes
    )
    await interaction.response.send_message(
        embed=base_embed(
            f"🚔 Arrest — {suspect.display_name}",
            COLOUR_ALERT,
            "Pick the charges from the penal code below (you can select up to 15), then press **Confirm**.",
        ),
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="cite", description="Cite a suspect: pick charges from the penal code (up to 15 at once)")
@leo_only()
@app_commands.describe(suspect="The person being cited", notes="Optional officer notes")
async def cite(
    interaction: discord.Interaction,
    suspect: discord.Member,
    notes: str | None = None,
) -> None:
    view = ChargeSelectView(kind="cite", officer=interaction.user, suspect=suspect, notes=notes)
    await interaction.response.send_message(
        embed=base_embed(
            f"🎫 Citation — {suspect.display_name}",
            COLOUR_STAFF,
            "Pick the charges from the penal code below (you can select up to 15), then press **Confirm**.",
        ),
        view=view,
        ephemeral=True,
    )


async def _purge_bot_session_messages(channel: discord.TextChannel, keep_first_overall: bool = False) -> int:
    """Delete the SCRS bot's own session messages in a channel. Returns the count."""
    keep_id = None
    if keep_first_overall:
        async for msg in channel.history(limit=1, oldest_first=True):
            keep_id = msg.id
    deleted = 0
    async for msg in channel.history(limit=250):
        if bot.user is None or msg.author.id != bot.user.id:
            continue
        if msg.pinned or (keep_id is not None and msg.id == keep_id):
            continue
        try:
            await msg.delete()
            deleted += 1
        except discord.HTTPException:
            pass
    return deleted


@bot.tree.command(name="sessionend", description="End the session: post the ended announcement and clean up session channels")
@staff_only()
@app_commands.describe(
    notes="Any closing notes for the session-ended post",
    cleanup="Also delete the bot's session posts in #startup / #early-access / #911 (keeps the first-ever #startup message)",
)
async def sessionend(interaction: discord.Interaction, notes: str = "", cleanup: bool = True) -> None:
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    results: dict[str, int] = {}
    if cleanup:
        for name, keep_first in (("startup", True), ("early-access", False), ("911", False)):
            channel = find_channel(guild, name)
            if channel:
                results[name] = await _purge_bot_session_messages(channel, keep_first_overall=keep_first)

    embed = base_embed(
        "🔴 Session Ended — SCRS",
        COLOUR_ALERT,
        "This roleplay session is **over**. Thanks to everyone who joined — see you at the next startup!",
    )
    embed.add_field(name="Ended by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Status", value="🔴 Ended", inline=True)
    if notes:
        embed.add_field(name="Notes", value=notes, inline=False)
    target = find_channel(guild, "startup") or interaction.channel
    await target.send(embed=embed)

    if cleanup:
        summary = ", ".join(f"#{name}: {count} deleted" for name, count in results.items()) or "nothing to clean"
        await interaction.followup.send(
            f"🔴 Session ended and posted in {target.mention}. Cleanup — {summary}. "
            "The first-ever message in #startup was kept.",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(f"🔴 Session ended and posted in {target.mention}.", ephemeral=True)


# --------------------------------------------------------------------------- #
# Staff Team — special roleplay requests
# --------------------------------------------------------------------------- #


class SpecialRPView(discord.ui.View):
    """Accept / Deny buttons on a special RP request (Management only)."""

    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=None)
        self.requester_id = requester_id
        self.decided = False

    async def _decide(self, interaction: discord.Interaction, accepted: bool) -> None:
        member = interaction.user
        allowed = isinstance(member, discord.Member) and (
            member.guild_permissions.administrator
            or has_any_role(member, {"Management"} | HIGH_RANK_ROLES)
        )
        if not allowed:
            await interaction.response.send_message(
                "Only **Management** (or High Rank) can accept or deny special RP requests.",
                ephemeral=True,
            )
            return
        if self.decided:
            await interaction.response.send_message("This request was already decided.", ephemeral=True)
            return
        self.decided = True

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else base_embed("Special RP Request", COLOUR_MAIN)
        embed.colour = COLOUR_OK if accepted else COLOUR_ALERT
        status_text = "✅ ACCEPTED" if accepted else "❌ DENIED"
        # Replace any existing Status field, then set the new one.
        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.remove_field(i)
                break
        embed.add_field(name="Status", value=f"{status_text} by {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # Record the decision.
        for record in store["special_rp_requests"]:
            if record.get("requester") == self.requester_id and record.get("status") == "pending":
                record["status"] = "accepted" if accepted else "denied"
                record["decided_by"] = interaction.user.id
                break
        save_store(store)

        # DM the requesting staff member the result.
        guild = interaction.guild
        requester = guild.get_member(self.requester_id) if guild else None
        rp_type = next(
            (f.value for f in embed.fields if f.name == "Special Roleplay"),
            "your special roleplay",
        )
        if requester:
            dm = base_embed(
                f"{status_text.split()[0]} Special RP Request {status_text.split()[-1]}",
                COLOUR_OK if accepted else COLOUR_ALERT,
            )
            dm.add_field(name="Special Roleplay", value=rp_type, inline=False)
            dm.add_field(name="Decision by", value=interaction.user.mention, inline=False)
            dm.description = (
                "Your special roleplay request was **accepted** — you're clear to run it. 🎬"
                if accepted
                else "Your special roleplay request was **denied** by management this time."
            )
            await safe_dm(requester, dm)


    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="scrs_rp_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, True)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="scrs_rp_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, False)


async def get_special_rp_channel(guild: discord.Guild) -> discord.TextChannel | None:
    channel = find_channel(guild, SPECIAL_RP_CHANNEL_NAME)
    if channel:
        return channel
    category = None
    for cat in guild.categories:
        if "staff" in cat.name.lower():
            category = cat
            break
    try:
        return await guild.create_text_channel(
            name=SPECIAL_RP_CHANNEL_NAME,
            category=category,
            topic="Special roleplay requests for SCRS (posted by the SCRS bot)",
            reason="SCRS bot: special-rp-request channel required by spec",
        )
    except discord.HTTPException:
        return None


@bot.tree.command(name="specialrpreq", description="Request a special roleplay — pick the type from the dropdown")
@staff_only()
@app_commands.describe(
    roleplay="Which special roleplay? (pick from the dropdown)",
    details="Describe the roleplay you want to run",
    when="When do you want to run it? (optional)",
)
@app_commands.choices(
    roleplay=[app_commands.Choice(name=t, value=t) for t in SPECIAL_RP_TYPES]
)
async def specialrpreq(
    interaction: discord.Interaction,
    roleplay: app_commands.Choice[str],
    details: str,
    when: str = "",
) -> None:
    guild = interaction.guild
    target = await get_special_rp_channel(guild)
    if target is None:
        await interaction.response.send_message(
            embed=base_embed(
                "❌ No request channel",
                COLOUR_ALERT,
                f"Couldn't find or create #{SPECIAL_RP_CHANNEL_NAME} — a server admin may need to create it.",
            ),
            ephemeral=True,
        )
        return

    embed = base_embed("🎬 Special Roleplay Request", COLOUR_EA)
    embed.add_field(name="Special Roleplay", value=roleplay.value, inline=False)
    embed.add_field(name="Requested by", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=False)
    embed.add_field(name="Details", value=details, inline=False)
    if when:
        embed.add_field(name="When", value=when, inline=False)
    embed.add_field(name="Status", value="⏳ Pending — Management, use the buttons below.", inline=False)

    management = find_role(guild, "Management")
    # Ping Management exactly once, in the message content.
    message = await target.send(
        content=management.mention if management else None,
        embed=embed,
        view=SpecialRPView(interaction.user.id),
    )

    store["special_rp_requests"].append(
        {
            "requester": interaction.user.id,
            "type": roleplay.value,
            "details": details,
            "when": when,
            "status": "pending",
            "message_id": message.id,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_store(store)
    await interaction.response.send_message(
        f"✅ Your **{roleplay.value}** request was sent to {target.mention} — Management has been pinged. "
        "You'll get a DM when they accept or deny it.",
        ephemeral=True,
    )


# --------------------------------------------------------------------------- #
# Civilian — profile, cars, 911
# --------------------------------------------------------------------------- #


@bot.tree.command(name="profile", description="Show a user's profile — dropdown for Tickets / Cars / Warrants")
@civilian_only()
@app_commands.describe(user="Whose profile to show (default: you)")
async def profile(interaction: discord.Interaction, user: discord.Member | None = None) -> None:
    member = user or interaction.user
    await interaction.response.send_message(embed=profile_embed(member), view=ProfileView(member))


@bot.tree.command(name="registercar", description="Register a car: Car Name / Color / Plate")
@civilian_only()
@app_commands.describe(car_name="Car name (make & model)", color="Car color", plate="License plate")
async def registercar(interaction: discord.Interaction, car_name: str, color: str, plate: str) -> None:
    plate_norm = re.sub(r"\s+", "", plate).upper()
    # A plate can only be registered to one person server-wide.
    for owner_id, cars in store["cars"].items():
        for car in cars:
            if car.get("plate") == plate_norm:
                if owner_id == str(interaction.user.id):
                    await interaction.response.send_message(
                        f"You already registered plate `{plate_norm}`.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"Plate `{plate_norm}` is already registered to someone else.", ephemeral=True
                    )
                return

    cars = store["cars"].setdefault(str(interaction.user.id), [])
    cars.append(
        {
            "car_name": car_name.strip(),
            "color": color.strip(),
            "plate": plate_norm,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["cars"][str(interaction.user.id)] = cars
    save_store(store)

    embed = base_embed("🚗 Car Registered", COLOUR_OK)
    embed.add_field(name="Owner", value=interaction.user.mention, inline=False)
    embed.add_field(name="Car Name", value=car_name, inline=True)
    embed.add_field(name="Color", value=color, inline=True)
    embed.add_field(name="Plate", value=f"`{plate_norm}`", inline=True)
    embed.add_field(name="Your cars", value=str(len(cars)), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unregistercar", description="Unregister one of your cars by its plate")
@civilian_only()
@app_commands.describe(plate="License plate of the car to remove")
async def unregistercar(interaction: discord.Interaction, plate: str) -> None:
    plate_norm = re.sub(r"\s+", "", plate).upper()
    cars = store["cars"].get(str(interaction.user.id), [])
    remaining = [c for c in cars if c.get("plate") != plate_norm]
    if len(remaining) == len(cars):
        await interaction.response.send_message(
            f"You don't have a car with plate `{plate_norm}` registered.", ephemeral=True
        )
        return
    removed = next(c for c in cars if c.get("plate") == plate_norm)
    store["cars"][str(interaction.user.id)] = remaining
    save_store(store)

    embed = base_embed("🗑️ Car Unregistered", COLOUR_INFO)
    embed.add_field(name="Owner", value=interaction.user.mention, inline=False)
    embed.add_field(name="Car Name", value=removed.get("car_name", "—"), inline=True)
    embed.add_field(name="Color", value=removed.get("color", "—"), inline=True)
    embed.add_field(name="Plate", value=f"`{plate_norm}`", inline=True)
    embed.add_field(name="Your cars now", value=str(len(remaining)), inline=True)
    await interaction.response.send_message(embed=embed)


# Emergency-service roles, hooked up to the roles Vaydin created in SCRS
# (checked in Server Settings on Oct 30, 2026):
#   Police  -> "Sarasota Police Department"
#   Sheriff -> "Sarasota County"  (the county role — Sarasota County Sheriff)
#   Fire    -> "Sarasota Fire Department"
# The bot tries the exact names first, then falls back to a partial-name
# match ("police" / "sheriff" / "county" / "fire" anywhere in a role name),
# then to the generic names, so renames don't break 911 pings.
SERVICE_ROLE_CANDIDATES = {
    "police": ["Sarasota Police Department", "Police", "Police Department", "PD"],
    "sheriff": [
        "Sarasota County",
        "Sarasota County Sheriff",
        "Sarasota County Sheriff's Office",
        "Sheriff",
        "Sheriff's Office",
        "Sheriff Department",
        "Sheriff Office",
    ],
    "fire": ["Sarasota Fire Department", "Fire Department", "Fire", "Fire Dept", "Fire/EMS", "FD", "EMS"],
}
SERVICE_LABELS = {"police": "🚓 Police", "sheriff": "⭐ Sheriff", "fire": "🚒 Fire Department"}
_SERVICE_FUZZY = {"police": ("police",), "sheriff": ("sheriff", "county"), "fire": ("fire",)}


def find_service_role(guild: discord.Guild, key: str) -> discord.Role | None:
    role = find_role(guild, *SERVICE_ROLE_CANDIDATES[key])
    if role:
        return role
    for candidate in guild.roles:
        lname = candidate.name.lower()
        if any(needle in lname for needle in _SERVICE_FUZZY[key]):
            return candidate
    return None


@bot.tree.command(name="911", description="Make a 911 call — choose Police, Sheriff or Fire")
@civilian_only()
@app_commands.describe(
    service="Who are you calling?",
    location="Where is the emergency?",
    situation="What's happening?",
)
@app_commands.choices(
    service=[
        app_commands.Choice(name="🚓 Police", value="police"),
        app_commands.Choice(name="⭐ Sheriff", value="sheriff"),
        app_commands.Choice(name="🚒 Fire Department", value="fire"),
        app_commands.Choice(name="🚨 All Services", value="all"),
    ]
)
async def nine_one_one(
    interaction: discord.Interaction,
    service: app_commands.Choice[str],
    location: str,
    situation: str,
) -> None:
    guild = interaction.guild
    chosen = (
        ["police", "sheriff", "fire"] if service.value == "all" else [service.value]
    )

    ping_roles: list[discord.Role] = []
    missing: list[str] = []
    for key in chosen:
        role = find_service_role(guild, key)
        if role:
            ping_roles.append(role)
        else:
            missing.append(SERVICE_LABELS[key])
    fallback_note = ""
    if not ping_roles:
        fallback = find_role(guild, "Emergency Services")
        if fallback:
            ping_roles.append(fallback)
            fallback_note = " (their dedicated role wasn't found yet, so Emergency Services was pinged)"
    elif missing:
        fallback_note = f" (no role found yet for: {', '.join(missing)})"

    embed = base_embed("🚨 911 CALL — Emergency Services Needed", COLOUR_ALERT)
    embed.add_field(name="Caller", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=False)
    embed.add_field(name="Location", value=location, inline=False)
    embed.add_field(name="Situation", value=situation, inline=False)
    embed.add_field(
        name="Service Requested",
        value=" • ".join(SERVICE_LABELS[k] for k in chosen) + fallback_note,
        inline=False,
    )
    embed.add_field(name="Status", value="⏳ Awaiting a unit — press **Responding** below if you're en route.", inline=False)

    target = find_channel(guild, "911") or interaction.channel
    content = " ".join(role.mention for role in ping_roles) or None
    await target.send(content=content, embed=embed, view=NineOneOneView())
    await interaction.response.send_message(
        f"🚨 Your 911 call for **{' / '.join(SERVICE_LABELS[k] for k in chosen)}** was sent to {target.mention} — help is on the way.",
        ephemeral=True,
    )
    # Voice dispatch: if a voice session is live, read the call out in RTO.
    _session = VOICE_SESSIONS.get(guild.id)
    if _session:
        _labels = " and ".join(SERVICE_LABELS[k].split(" ", 1)[-1] for k in chosen)
        asyncio.create_task(
            _speak(
                _session,
                f"911 call. {_labels} requested. Location: {location}. Situation: {situation}.",
            )
        )


# --------------------------------------------------------------------------- #
# Voice assistant (Groq) — /voicejoin + /voiceleave
#
# The bot joins a voice channel (RTO by default), listens to High Rank
# speakers, transcribes with Groq Whisper, parses commands with a Groq LLM
# (tool calling), asks for spoken confirmation before anything destructive,
# executes, and answers out loud with Groq Orpheus TTS. 911 calls are also
# read aloud while a voice session is active. Needs GROQ_API_KEY in .env
# plus the discord-ext-voice-recv package; without them the rest of the bot
# works normally and only the voice commands report what's missing.
# --------------------------------------------------------------------------- #

import asyncio
import io
import wave

try:
    import aiohttp
except ImportError:  # discord.py already depends on aiohttp; this is belt & braces
    aiohttp = None

try:
    from discord.ext import voice_recv

    VOICE_RECV_AVAILABLE = True
except Exception:
    voice_recv = None
    VOICE_RECV_AVAILABLE = False

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-120b")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_TTS_MODEL = os.getenv("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
GROQ_TTS_VOICE = os.getenv("GROQ_TTS_VOICE", "autumn")

VOICE_SESSIONS: dict[int, dict] = {}
CONFIRM_WORDS = {"confirm", "confirmed", "yes", "yeah", "yep", "do it", "go ahead", "proceed", "affirmative"}
CANCEL_WORDS = {"cancel", "no", "stop", "never mind", "nevermind", "abort", "forget it"}


def _groq_headers() -> dict:
    return {"Authorization": f"Bearer {GROQ_API_KEY}"}


async def groq_transcribe(wav_bytes: bytes) -> str:
    """Speech -> text via Groq Whisper."""
    if aiohttp is None:
        return ""
    form = aiohttp.FormData()
    form.add_field("file", wav_bytes, filename="utterance.wav", content_type="audio/wav")
    form.add_field("model", GROQ_STT_MODEL)
    form.add_field("response_format", "json")
    async with aiohttp.ClientSession() as http:
        async with http.post(
            f"{GROQ_BASE}/audio/transcriptions",
            headers=_groq_headers(),
            data=form,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                print(f"[SCRS] Groq STT error {resp.status}: {(await resp.text())[:200]}", file=sys.stderr)
                return ""
            data = await resp.json()
    return str(data.get("text", "")).strip()


VOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "give_infraction",
            "description": "Give a player an infraction (discipline record + Infraction role). Use when the speaker asks to infract/infraction a player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "description": "The player's name exactly as spoken"},
                    "reason": {"type": "string", "description": "Why they are being infracted"},
                },
                "required": ["member", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "give_strike",
            "description": "Give a staff member a strike (punish). Use when the speaker asks to strike/punish a staff member.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "description": "The staff member's name exactly as spoken"},
                    "reason": {"type": "string", "description": "Why they are receiving the strike"},
                },
                "required": ["member", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "issue_ticket",
            "description": "Issue a citation/ticket with a fine amount to a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "description": "The user's name exactly as spoken"},
                    "reason": {"type": "string", "description": "Reason for the ticket"},
                    "penal_code": {"type": "string", "description": "Penal code, if mentioned; otherwise 'N/A'"},
                    "amount": {"type": "integer", "description": "Fine amount in dollars"},
                },
                "required": ["member", "reason", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "issue_warrant",
            "description": "Put an arrest warrant on a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "description": "The user's name exactly as spoken"},
                    "reason": {"type": "string", "description": "Reason for the warrant"},
                },
                "required": ["member", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "say_message",
            "description": "Make the bot post a text message in the staff text channel. Use when the speaker asks the bot to say/write/announce something in text.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "The exact message to post"}},
                "required": ["message"],
            },
        },
    },
]

VOICE_SYSTEM_PROMPT = (
    "You are the voice command parser for the SCRS roleplay staff bot. A staff member is speaking in a "
    "voice channel. If — and only if — their utterance is a clear request to perform one of the available "
    "actions, call the matching function with the arguments taken from what they said. Names must be copied "
    "exactly as spoken. If the utterance is ordinary conversation, a question, or not a clear command, do "
    "NOT call any function and return an empty reply. Never invent a member name, reason, or amount that "
    "was not said."
)


async def groq_parse_command(transcript: str) -> dict | None:
    """Text -> {name, arguments} tool call, or None if it isn't a command."""
    if aiohttp is None:
        return None
    payload = {
        "model": GROQ_LLM_MODEL,
        "messages": [
            {"role": "system", "content": VOICE_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        "tools": VOICE_TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(
            f"{GROQ_BASE}/chat/completions",
            headers={**_groq_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                print(f"[SCRS] Groq LLM error {resp.status}: {(await resp.text())[:200]}", file=sys.stderr)
                return None
            data = await resp.json()
    try:
        calls = data["choices"][0]["message"].get("tool_calls") or []
        if not calls:
            return None
        fn = calls[0]["function"]
        return {"name": fn["name"], "arguments": json.loads(fn.get("arguments") or "{}")}
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


async def groq_speak_wav(text: str) -> bytes | None:
    """Text -> WAV audio bytes via Groq Orpheus TTS (max 200 chars per request)."""
    if aiohttp is None:
        return None
    payload = {
        "model": GROQ_TTS_MODEL,
        "voice": GROQ_TTS_VOICE,
        "input": text[:200],
        "response_format": "wav",
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(
            f"{GROQ_BASE}/audio/speech",
            headers={**_groq_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                print(f"[SCRS] Groq TTS error {resp.status}: {(await resp.text())[:200]}", file=sys.stderr)
                return None
            return await resp.read()


def _chunk_text(text: str, limit: int = 190) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for piece in ([sentence] if len(sentence) <= limit else [sentence[i : i + limit] for i in range(0, len(sentence), limit)]):
            if len(current) + len(piece) + 1 <= limit:
                current = f"{current} {piece}".strip()
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


async def voice_log(guild: discord.Guild, text: str) -> None:
    """Audit trail for voice activity -> #bot-logs. Never raises."""
    try:
        channel = guild.get_channel(BOT_LOGS_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(BOT_LOGS_CHANNEL_ID)
        await channel.send(f"🎙️ {text}")
    except Exception:
        pass


def resolve_member(guild: discord.Guild, query: str) -> tuple[discord.Member | None, list[str]]:
    """Find a member by spoken name. Returns (member, ambiguous_names)."""
    q = (query or "").strip().lower().lstrip("@")
    if not q:
        return None, []
    members = [m for m in guild.members if not m.bot]
    for m in members:
        if q in {m.name.lower(), m.display_name.lower(), str(m).lower()}:
            return m, []
    partial = [m for m in members if q in m.display_name.lower() or q in m.name.lower()]
    if len(partial) == 1:
        return partial[0], []
    if len(partial) > 1:
        return None, [m.display_name for m in partial[:5]]
    words = q.split()
    scored = [m for m in members if any(w in m.display_name.lower() for w in words)]
    if len(scored) == 1:
        return scored[0], []
    return None, []


def _pcm_to_wav(pcm: bytes) -> bytes:
    """Voice-recv PCM is 48kHz / 16-bit / stereo."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(pcm)
    return buf.getvalue()


class UtteranceSink(voice_recv.sinks.AudioSink if VOICE_RECV_AVAILABLE else object):
    """Buffers each speaker's PCM; the session watcher flushes on silence."""

    def __init__(self, session: dict) -> None:
        if VOICE_RECV_AVAILABLE:
            super().__init__()
        self.session = session
        self.buffers: dict[int, dict] = {}

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:
        if user is None or getattr(user, "bot", False):
            return
        entry = self.buffers.setdefault(user.id, {"pcm": bytearray(), "last": 0.0, "member": user})
        try:
            entry["pcm"] += data.pcm
        except Exception:
            return
        entry["last"] = time.time()
        entry["member"] = user

    def cleanup(self) -> None:
        self.buffers.clear()


async def _speak(session: dict, text: str) -> None:
    """Speak text in the session's voice channel (TTS), text fallback in chat."""
    vc = session["vc"]
    async with session["speak_lock"]:
        for chunk in _chunk_text(text):
            wav_bytes = await groq_speak_wav(chunk)
            if not wav_bytes:
                try:
                    await session["text_channel"].send(f"🔊 {chunk}")
                except Exception:
                    pass
                continue
            path = None
            try:
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(wav_bytes)
                    path = tmp.name
                if not vc.is_connected():
                    return
                vc.play(discord.FFmpegPCMAudio(path))
                while vc.is_playing():
                    await asyncio.sleep(0.2)
            except Exception as exc:
                print(f"[SCRS] Voice playback error: {exc}", file=sys.stderr)
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass


async def _apply_voice_action(session: dict, action: dict) -> str:
    """Execute a confirmed voice action. Returns a short spoken result."""
    guild: discord.Guild = session["guild"]
    actor: discord.Member = action["speaker"]
    name = action["name"]
    args = action["arguments"]

    if name == "say_message":
        await session["text_channel"].send(str(args.get("message", ""))[:2000])
        await voice_log(guild, f"Voice /say by {actor}: {str(args.get('message', ''))[:150]}")
        return "Message sent."

    target = action.get("member_obj")
    if target is None:
        return "I couldn't find that member."

    if name == "give_infraction":
        records = store["infractions"].setdefault(str(target.id), [])
        level = min(len(records) + 1, 3)
        role_note = ""
        role = find_role(guild, f"Infraction {level}")
        if role:
            try:
                if role not in target.roles:
                    await target.add_roles(role, reason=f"Infraction {level} via voice by {actor}")
                role_note = f"Added role: **Infraction {level}**"
            except discord.Forbidden:
                role_note = "⚠️ Couldn't add the Infraction role (bot role too low)."
        records.append(
            {"by": actor.id, "reason": args.get("reason", ""), "proof": "Voice command", "level": level, "at": datetime.now(timezone.utc).isoformat()}
        )
        store["infractions"][str(target.id)] = records
        save_store(store)
        embed = base_embed("⚠️ Infraction Issued (voice command)", COLOUR_ALERT)
        embed.add_field(name="Player", value=f"{target.mention} ({target.display_name})", inline=False)
        embed.add_field(name="Infraction", value=f"Infraction {level} of 3", inline=True)
        embed.add_field(name="Issued by", value=f"{actor.mention} (voice)", inline=True)
        embed.add_field(name="Reason", value=args.get("reason", ""), inline=False)
        if role_note:
            embed.add_field(name="Role", value=role_note, inline=False)
        await session["text_channel"].send(embed=embed)
        await log_punishment(guild, embed)
        await safe_dm(target, embed)
        await voice_log(guild, f"Voice infraction {level} -> {target} by {actor}: {args.get('reason', '')}")
        return f"Done. Infraction {level} given to {target.display_name}."

    if name == "give_strike":
        records = store["strikes"].setdefault(str(target.id), [])
        level = min(len(records) + 1, 3)
        new_role = find_role(guild, f"Staff Strike {level}")
        if new_role:
            try:
                for old_level in (1, 2, 3):
                    old_role = find_role(guild, f"Staff Strike {old_level}")
                    if old_role and old_role in target.roles and old_role != new_role:
                        await target.remove_roles(old_role, reason="Superseded by higher strike")
                if new_role not in target.roles:
                    await target.add_roles(new_role, reason=f"Staff Strike {level} via voice by {actor}")
            except discord.Forbidden:
                pass
        records.append(
            {"by": actor.id, "reason": args.get("reason", ""), "proof": "Voice command", "level": level, "at": datetime.now(timezone.utc).isoformat()}
        )
        store["strikes"][str(target.id)] = records
        save_store(store)
        embed = base_embed("🔨 Staff Strike Issued (voice command)", COLOUR_ALERT)
        embed.add_field(name="Staff Member", value=f"{target.mention} ({target.display_name})", inline=False)
        embed.add_field(name="Strike", value=f"Staff Strike {level} of 3", inline=True)
        embed.add_field(name="Issued by", value=f"{actor.mention} (voice)", inline=True)
        embed.add_field(name="Reason", value=args.get("reason", ""), inline=False)
        await session["text_channel"].send(embed=embed)
        await log_punishment(guild, embed)
        await safe_dm(target, embed)
        await voice_log(guild, f"Voice strike {level} -> {target} by {actor}: {args.get('reason', '')}")
        return f"Done. Strike {level} given to {target.display_name}."

    if name == "issue_ticket":
        amount = int(args.get("amount", 0))
        records = store["citations"].setdefault(str(target.id), [])
        records.append(
            {"by": actor.id, "reason": args.get("reason", ""), "penal_code": args.get("penal_code", "N/A"), "amount": amount, "at": datetime.now(timezone.utc).isoformat()}
        )
        store["citations"][str(target.id)] = records
        save_store(store)
        embed = base_embed("🎫 Ticket Issued (voice command)", COLOUR_STAFF)
        embed.add_field(name="User", value=f"{target.mention} ({target.display_name})", inline=False)
        embed.add_field(name="Reason", value=args.get("reason", ""), inline=False)
        embed.add_field(name="Penal Code", value=str(args.get("penal_code", "N/A")), inline=True)
        embed.add_field(name="Amount", value=f"${amount:,}", inline=True)
        embed.add_field(name="Issued by", value=f"{actor.mention} (voice)", inline=True)
        await session["text_channel"].send(embed=embed)
        await log_punishment(guild, embed)
        await safe_dm(target, embed)
        await voice_log(guild, f"Voice ticket ${amount} -> {target} by {actor}: {args.get('reason', '')}")
        return f"Done. Citation of {amount} dollars issued to {target.display_name}."

    if name == "issue_warrant":
        records = store["warrants"].setdefault(str(target.id), [])
        records.append({"by": actor.id, "reason": args.get("reason", ""), "at": datetime.now(timezone.utc).isoformat(), "active": True})
        store["warrants"][str(target.id)] = records
        save_store(store)
        embed = base_embed("📜 Warrant Issued (voice command)", COLOUR_ALERT)
        embed.add_field(name="User", value=f"{target.mention} ({target.display_name})", inline=False)
        embed.add_field(name="Reason", value=args.get("reason", ""), inline=False)
        embed.add_field(name="Issued by", value=f"{actor.mention} (voice)", inline=True)
        embed.add_field(name="Status", value="🔴 ACTIVE", inline=False)
        await session["text_channel"].send(embed=embed)
        await log_punishment(guild, embed)
        await safe_dm(target, embed)
        await voice_log(guild, f"Voice warrant -> {target} by {actor}: {args.get('reason', '')}")
        return f"Done. Warrant issued for {target.display_name}."

    return "That action isn't supported by voice yet."


def _summarize_action(action: dict) -> str:
    name, args = action["name"], action["arguments"]
    target = action.get("member_obj")
    tname = target.display_name if target else args.get("member", "?")
    if name == "give_infraction":
        return f"Infraction for {tname}. Reason: {args.get('reason', '')}."
    if name == "give_strike":
        return f"Staff strike for {tname}. Reason: {args.get('reason', '')}."
    if name == "issue_ticket":
        return f"Citation for {tname}, {int(args.get('amount', 0))} dollars. Reason: {args.get('reason', '')}."
    if name == "issue_warrant":
        return f"Warrant for {tname}. Reason: {args.get('reason', '')}."
    if name == "say_message":
        return f"Posting the message: {str(args.get('message', ''))[:120]}"
    return name


async def _process_utterance(session: dict, member: discord.Member, pcm: bytes) -> None:
    if not isinstance(member, discord.Member) or not passes(member, HIGH_RANK_ROLES):
        return  # only High Rank / admins can drive the bot by voice
    wav_bytes = _pcm_to_wav(pcm)
    transcript = await groq_transcribe(wav_bytes)
    if len(transcript) < 3:
        return
    await voice_log(session["guild"], f"🗣️ {member.display_name}: “{transcript[:200]}”")
    lowered = " ".join(transcript.lower().strip(" .!?").split())

    pending = session.get("pending")
    if pending and pending["speaker_id"] == member.id:
        if time.time() <= pending["expires"]:
            if lowered in CONFIRM_WORDS or lowered.startswith("confirm"):
                session["pending"] = None
                result = await _apply_voice_action(session, pending["action"])
                await _speak(session, result)
                return
            if lowered in CANCEL_WORDS:
                session["pending"] = None
                await _speak(session, "Cancelled.")
                return
        else:
            session["pending"] = None

    parsed = await groq_parse_command(transcript)
    if not parsed:
        return
    action = {"name": parsed["name"], "arguments": parsed.get("arguments", {}), "speaker": member}
    if action["name"] != "say_message":
        member_obj, ambiguous = resolve_member(session["guild"], str(action["arguments"].get("member", "")))
        if member_obj is None:
            if ambiguous:
                await _speak(session, f"That name matches several people: {', '.join(ambiguous)}. Please be more specific.")
            else:
                await _speak(session, f"I couldn't find a member named {action['arguments'].get('member', '')}.")
            return
        action["member_obj"] = member_obj

    if action["name"] == "say_message":
        result = await _apply_voice_action(session, action)
        await _speak(session, result)
        return

    summary = _summarize_action(action)
    session["pending"] = {
        "action": action,
        "speaker_id": member.id,
        "expires": time.time() + 30,
    }
    try:
        await session["text_channel"].send(
            embed=base_embed("🎙️ Voice command — confirmation needed", COLOUR_INFO, f"**{summary}**\n{member.mention}: say **“confirm”** within 30 seconds to execute, or “cancel”.")
        )
    except Exception:
        pass
    await _speak(session, f"{summary} Say confirm to proceed, or cancel.")


async def _voice_watcher(session: dict) -> None:
    """Flush a speaker's buffer after ~1.1s of silence and process it."""
    sink: UtteranceSink = session["sink"]
    BYTES_PER_SECOND = 48000 * 2 * 2  # 48kHz, stereo, 16-bit
    while True:
        await asyncio.sleep(0.3)
        vc = session["vc"]
        if not vc.is_connected():
            break
        now = time.time()
        for user_id, entry in list(sink.buffers.items()):
            if entry["last"] and now - entry["last"] >= 1.1:
                pcm = bytes(entry["pcm"])
                member = entry["member"]
                sink.buffers.pop(user_id, None)
                if len(pcm) >= int(BYTES_PER_SECOND * 0.35):
                    asyncio.create_task(_process_utterance(session, member, pcm))
    VOICE_SESSIONS.pop(session["guild"].id, None)


async def _end_voice_session(guild_id: int) -> None:
    session = VOICE_SESSIONS.pop(guild_id, None)
    if not session:
        return
    task = session.get("watcher")
    if task:
        task.cancel()
    try:
        session["vc"].stop_listening()
    except Exception:
        pass
    try:
        await session["vc"].disconnect(force=True)
    except Exception:
        pass


@bot.tree.command(name="voicejoin", description="Join your voice channel and enable Groq voice commands (High Rank)")
@high_rank_only()
@app_commands.describe(channel="Voice channel to join (default: yours, or the RTO channel)")
async def voicejoin(interaction: discord.Interaction, channel: discord.VoiceChannel | None = None) -> None:
    if not VOICE_RECV_AVAILABLE:
        await interaction.response.send_message(
            "🎙️ Voice receiving isn't available on this host yet — the `discord-ext-voice-recv` package needs to be installed (it's in requirements.txt; restart the server after updating it).",
            ephemeral=True,
        )
        return
    if not GROQ_API_KEY:
        await interaction.response.send_message(
            "🎙️ `GROQ_API_KEY` isn't set in the bot's environment (.env on Katabump). Add it and restart, then try again.",
            ephemeral=True,
        )
        return
    guild = interaction.guild
    if guild.id in VOICE_SESSIONS:
        await interaction.response.send_message("🎙️ A voice session is already active in this server. Use /voiceleave first.", ephemeral=True)
        return
    target = channel
    if target is None and isinstance(interaction.user, discord.Member) and interaction.user.voice:
        target = interaction.user.voice.channel
    if target is None:
        for ch in guild.voice_channels:
            if "rto" in ch.name.lower():
                target = ch
                break
    if target is None:
        await interaction.response.send_message("🎙️ Join a voice channel first, or pick one with the channel option.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        vc = await target.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False, timeout=30)
    except Exception as exc:
        await interaction.followup.send(f"🎙️ Couldn't join {target.mention}: {exc}", ephemeral=True)
        return

    session = {
        "guild": guild,
        "vc": vc,
        "text_channel": interaction.channel,
        "pending": None,
        "speak_lock": asyncio.Lock(),
    }
    sink = UtteranceSink(session)
    session["sink"] = sink
    vc.listen(sink)
    session["watcher"] = asyncio.create_task(_voice_watcher(session))
    VOICE_SESSIONS[guild.id] = session
    await voice_log(guild, f"Voice session started in **{target.name}** by {interaction.user}.")
    await interaction.followup.send(
        f"🎙️ Voice assistant active in {target.mention}. High Rank members can speak commands now — destructive actions ask for a spoken “confirm” first. 911 calls will be read aloud here.",
        ephemeral=True,
    )
    await _speak(session, "Voice assistant online. I am listening for staff commands.")


@bot.tree.command(name="voiceleave", description="Stop the voice assistant and leave the voice channel")
@high_rank_only()
async def voiceleave(interaction: discord.Interaction) -> None:
    if interaction.guild.id not in VOICE_SESSIONS:
        await interaction.response.send_message("🎙️ No voice session is active.", ephemeral=True)
        return
    await _end_voice_session(interaction.guild.id)
    await voice_log(interaction.guild, f"Voice session ended by {interaction.user}.")
    await interaction.response.send_message("🎙️ Voice assistant off — left the channel.", ephemeral=True)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not TOKEN:
        print(
            "[SCRS] ERROR: DISCORD_TOKEN is not set.\n"
            "  • On Katabump: add DISCORD_TOKEN in your server's startup / environment settings,\n"
            "    or keep the .env file with DISCORD_TOKEN in the server root.\n"
            "  • Locally: copy .env.example to .env and paste the token there.",
            file=sys.stderr,
        )
        sys.exit(1)
    bot.run(TOKEN)
