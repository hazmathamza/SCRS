"""
SCRS — Sunshine Coast Roleplay Server Discord Bot
===================================================
Built for the SCRS server (Sunshine Coast Roleplay Server, Roblox / SWFL RP).

Implements Vaydin's command spec (all prefix commands use "-"):

    -say        High Rank   Speak as the bot in any channel
    -startup    Staff Team  Announce a session startup
    -ea         Staff Team  Announce an Early Access session
    -release    Staff Team  Release a session to the public
    -setup      Staff Team  Post the session setup / how-to-join embed
    -infraction High Rank   Give a player an infraction (Infraction 1-3 roles)
    -punish     High Rank   Give a staff member a strike (Staff Strike 1-3)
    -profile    Civilian    Show a user's profile, registration & tickets
    -ticket     Civilian    Open a ticket (for yourself or another user)
    -911        Civilian    Place a 911 call to Sheriff / Police / Fire

Utility: -ping, -help, -close (inside ticket channels)

The token is read from the DISCORD_TOKEN environment variable (or a local
.env file for development). It is NEVER hard-coded.
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
from discord.ext import commands

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional on hosts that set real env vars
    pass

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PREFIX = os.getenv("BOT_PREFIX", "-")
GUILD_ID = int(os.getenv("GUILD_ID", "1515858046822252684"))

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "store.json"

# Role groups (exact role names in the SCRS server)
HIGH_RANK_ROLES = {
    "Owner",
    "Co Owner",
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

# Brand colours
COLOUR_MAIN = discord.Colour.from_rgb(255, 170, 0)      # SCRS amber
COLOUR_OK = discord.Colour.from_rgb(46, 204, 113)
COLOUR_ALERT = discord.Colour.from_rgb(231, 76, 60)
COLOUR_INFO = discord.Colour.from_rgb(52, 152, 219)
COLOUR_EA = discord.Colour.from_rgb(155, 89, 182)
COLOUR_STAFF = discord.Colour.from_rgb(241, 196, 15)

START_TIME = time.time()

# --------------------------------------------------------------------------- #
# Persistent store (JSON — survives restarts on Katabump's filesystem)
# --------------------------------------------------------------------------- #


def load_store() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"infractions": {}, "strikes": {}, "tickets": {}, "ticket_counter": 0}


def save_store(store: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


store = load_store()

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def has_any_role(member: discord.Member, names: set[str]) -> bool:
    return any(role.name in names for role in member.roles)


def is_admin(member: discord.Member) -> bool:
    return bool(member.guild_permissions and member.guild_permissions.administrator)


def passes(member: discord.Member, group: set[str]) -> bool:
    """Admins bypass role gates so server admins can always test/use commands."""
    return is_admin(member) or has_any_role(member, group)


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


def find_category(guild: discord.Guild, *needles: str) -> discord.CategoryChannel | None:
    for category in guild.categories:
        if any(n.lower() in category.name.lower() for n in needles):
            return category
    return None


async def log_to(guild: discord.Guild, channel_names: list[str], embed: discord.Embed) -> None:
    channel = find_channel(guild, *channel_names)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


def parse_reason_proof(text: str) -> tuple[str, str]:
    """
    Parse Vaydin's order — Reason: ... Proof: ... — flexibly:
      "Reason: speeding Proof: https://..."  -> ("speeding", "https://...")
      "speeding | https://..."               -> ("speeding", "https://...")
      "speeding"                             -> ("speeding", "Not provided")
    """
    text = (text or "").strip()
    text = re.sub(r"^\s*infraction\s*:\s*", "", text, flags=re.IGNORECASE)
    reason_match = re.search(r"reason\s*:\s*(.+?)(?=\bproof\s*:|$)", text, re.IGNORECASE | re.DOTALL)
    proof_match = re.search(r"proof\s*:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
    if reason_match or proof_match:
        reason = reason_match.group(1).strip() if reason_match else "Not specified"
        proof = proof_match.group(1).strip() if proof_match else "Not provided"
        return reason, proof
    if "|" in text:
        reason, proof = (part.strip() for part in text.split("|", 1))
        return reason or "Not specified", proof or "Not provided"
    return text or "Not specified", "Not provided"


def base_embed(title: str, colour: discord.Colour, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, colour=colour, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Sunshine Coast Roleplay Server • SCRS")
    return embed


def denied_embed(needed: str) -> discord.Embed:
    return base_embed(
        "⛔ You don't have permission for that",
        COLOUR_ALERT,
        f"This command needs the **{needed}** role (or Administrator).",
    )


# --------------------------------------------------------------------------- #
# Permission checks (used as decorators; raise CheckFailure when denied)
# --------------------------------------------------------------------------- #


def high_rank_only():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild and passes(ctx.author, HIGH_RANK_ROLES):
            return True
        raise commands.CheckFailure("high_rank")

    return commands.check(predicate)


def staff_only():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild and passes(ctx.author, STAFF_ROLES):
            return True
        raise commands.CheckFailure("staff")

    return commands.check(predicate)


def civilian_only():
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild and passes(ctx.author, CIVILIAN_ROLES):
            return True
        raise commands.CheckFailure("civilian")

    return commands.check(predicate)


# --------------------------------------------------------------------------- #
# Interactive views
# --------------------------------------------------------------------------- #


class SessionView(discord.ui.View):
    """Join button used on -startup / -ea / -release announcements."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.attendees: set[int] = set()

    @discord.ui.button(label="✅ I'm joining", style=discord.ButtonStyle.success, custom_id="scrs_session_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id in self.attendees:
            await interaction.response.send_message("You're already on the join list for this session.", ephemeral=True)
            return
        self.attendees.add(interaction.user.id)
        button.label = f"✅ I'm joining ({len(self.attendees)})"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("You're on the list — see you in session! 🚗", ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="scrs_ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = interaction.user
        if isinstance(member, discord.Member) and (
            member.id == self.owner_id or passes(member, STAFF_ROLES)
        ):
            await interaction.response.send_message("Closing this ticket in 3 seconds…")
            import asyncio

            await asyncio.sleep(3)
            await interaction.channel.delete(reason=f"Ticket closed by {member}")
        else:
            await interaction.response.send_message(
                "Only the ticket owner or staff can close this ticket.", ephemeral=True
            )


class NineOneOneView(discord.ui.View):
    """Lets Emergency Services claim a 911 call."""

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
# Bot
# --------------------------------------------------------------------------- #

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, case_insensitive=True, help_command=None)


@bot.event
async def on_ready() -> None:
    print(f"[SCRS] Logged in as {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        print(f"[SCRS] Serving guild: {guild.name} ({guild.id}) — {guild.member_count} members")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Sunshine Coast RP | -help")
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CheckFailure):
        needed = {"high_rank": "High Rank", "staff": "Staff Team", "civilian": "Civilian"}.get(
            str(error), "required"
        )
        await ctx.send(embed=denied_embed(needed), delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            embed=base_embed(
                "⚠️ Missing something",
                COLOUR_ALERT,
                f"You're missing the **{error.param.name}** part. Try `-help` to see the format.",
            ),
            delete_after=10,
        )
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(
            embed=base_embed("⚠️ Member not found", COLOUR_ALERT, "Mention a member of this server, e.g. `@User`."),
            delete_after=10,
        )
    elif isinstance(error, commands.CommandNotFound):
        pass  # Stay silent on unknown "-" text so normal chat isn't spammed
    else:
        print(f"[SCRS] Error in {ctx.command}: {error}", file=sys.stderr)
        await ctx.send(
            embed=base_embed("❌ Something went wrong", COLOUR_ALERT, "That command hit an error — staff have the details in the console log."),
            delete_after=10,
        )


# --------------------------------------------------------------------------- #
# Utility commands
# --------------------------------------------------------------------------- #


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    """Check the bot is alive."""
    uptime = int(time.time() - START_TIME)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    embed = base_embed("🏓 Pong!", COLOUR_OK)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
    embed.add_field(name="Server", value=ctx.guild.name if ctx.guild else "DM", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="help")
async def help_command(ctx: commands.Context) -> None:
    """List every SCRS command and who can use it."""
    embed = base_embed(
        "📖 SCRS Bot — Commands",
        COLOUR_MAIN,
        "All commands start with `-`. Buttons on announcements (Join / Responding / Close) are clickable.",
    )
    embed.add_field(
        name="🔊 High Rank",
        value=(
            "`-say [#channel] <message>` — speak as the bot\n"
            "`-infraction @user Reason: … Proof: …` — give a player infraction (adds Infraction 1–3)\n"
            "`-punish @user Reason: … Proof: …` — staff strike (adds Staff Strike 1–3)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛠️ Staff Team",
        value=(
            "`-startup [notes]` — announce a session startup in #startup\n"
            "`-ea [notes]` — announce an Early Access session in #early-access\n"
            "`-release [notes]` — release the session to everyone\n"
            "`-setup [join code]` — post how to join / set up for the session"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 Civilian (everyone)",
        value=(
            "`-profile [@user]` — profile, registration & ticket history\n"
            "`-ticket [@user] [reason]` — open a support ticket\n"
            "`-911 <location> | <what's happening>` — call Sheriff / Police / Fire"
        ),
        inline=False,
    )
    embed.add_field(name="⚙️ Utility", value="`-ping` — check the bot\n`-close` — close a ticket channel", inline=False)
    await ctx.send(embed=embed)


# --------------------------------------------------------------------------- #
# High Rank commands
# --------------------------------------------------------------------------- #


@bot.command(name="say")
@high_rank_only()
async def say(ctx: commands.Context, channel: discord.TextChannel | None = None, *, message: str) -> None:
    """
    -say <message>                  -> speak in this channel
    -say #channel <message>         -> speak in that channel
    """
    target = channel or ctx.channel
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    await target.send(message)


@bot.command(name="infraction")
@high_rank_only()
async def infraction(ctx: commands.Context, member: discord.Member, *, details: str = "") -> None:
    """
    -infraction @user Reason: <reason> Proof: <proof>
    Adds the next Infraction role (1, then 2, then 3) and logs it.
    """
    reason, proof = parse_reason_proof(details)
    records = store["infractions"].setdefault(str(member.id), [])
    level = min(len(records) + 1, 3)

    role_note = "No Infraction roles were found in this server."
    role = find_role(ctx.guild, f"Infraction {level}")
    if role:
        try:
            if role not in member.roles:
                await member.add_roles(role, reason=f"Infraction {level} by {ctx.author}: {reason}")
            role_note = f"Added role: **Infraction {level}**"
        except discord.Forbidden:
            role_note = f"⚠️ Couldn't add **Infraction {level}** — move the SCRS bot role above it and try again."

    records.append(
        {
            "by": ctx.author.id,
            "reason": reason,
            "proof": proof,
            "level": level,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["infractions"][str(member.id)] = records
    save_store(store)

    embed = base_embed("⚠️ Infraction Issued", COLOUR_ALERT)
    embed.add_field(name="Player", value=f"{member.mention} ({member.display_name})", inline=False)
    embed.add_field(name="Infraction", value=f"Infraction {level} of 3", inline=True)
    embed.add_field(name="Issued by", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Proof", value=proof, inline=False)
    embed.add_field(name="Role", value=role_note, inline=False)
    if level >= 3:
        embed.add_field(name="🚨 Escalation", value="This player is at **Infraction 3** — refer to High Rank for further action.", inline=False)
    await ctx.send(embed=embed)
    await log_to(ctx.guild, ["ticket-logs", "punishment-request", "hr-chat"], embed)
    try:
        await member.send(embed=embed)
    except discord.HTTPException:
        pass


@bot.command(name="punish")
@high_rank_only()
async def punish(ctx: commands.Context, member: discord.Member, *, details: str = "") -> None:
    """
    -punish @user Reason: <reason> Proof: <proof>
    Puts a staff strike on the user (Staff Strike 1, then 2, then 3).
    """
    reason, proof = parse_reason_proof(details)
    records = store["strikes"].setdefault(str(member.id), [])
    level = min(len(records) + 1, 3)

    role_note = "No Staff Strike roles were found in this server."
    new_role = find_role(ctx.guild, f"Staff Strike {level}")
    if new_role:
        try:
            for old_level in (1, 2, 3):
                old_role = find_role(ctx.guild, f"Staff Strike {old_level}")
                if old_role and old_role in member.roles and old_role != new_role:
                    await member.remove_roles(old_role, reason="Superseded by higher strike")
            if new_role not in member.roles:
                await member.add_roles(new_role, reason=f"Staff Strike {level} by {ctx.author}: {reason}")
            role_note = f"Added role: **Staff Strike {level}**"
        except discord.Forbidden:
            role_note = f"⚠️ Couldn't add **Staff Strike {level}** — move the SCRS bot role above it and try again."

    records.append(
        {
            "by": ctx.author.id,
            "reason": reason,
            "proof": proof,
            "level": level,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store["strikes"][str(member.id)] = records
    save_store(store)

    embed = base_embed("🔨 Staff Strike Issued", COLOUR_ALERT)
    embed.add_field(name="Staff Member", value=f"{member.mention} ({member.display_name})", inline=False)
    embed.add_field(name="Strike", value=f"Staff Strike {level} of 3", inline=True)
    embed.add_field(name="Issued by", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Proof", value=proof, inline=False)
    embed.add_field(name="Role", value=role_note, inline=False)
    if level >= 3:
        embed.add_field(
            name="🚨 Escalation",
            value="This is **Strike 3** — refer to High Rank / Management for a Staff Blacklist review.",
            inline=False,
        )
    await ctx.send(embed=embed)
    await log_to(ctx.guild, ["ticket-logs", "punishment-request", "hr-chat"], embed)
    try:
        await member.send(embed=embed)
    except discord.HTTPException:
        pass


# --------------------------------------------------------------------------- #
# Staff Team — session commands
# --------------------------------------------------------------------------- #


async def _post_session_embed(
    ctx: commands.Context,
    target_names: list[str],
    embed: discord.Embed,
    ping_role_names: list[str],
) -> None:
    target = find_channel(ctx.guild, *target_names) or ctx.channel
    ping = ""
    for name in ping_role_names:
        role = find_role(ctx.guild, name)
        if role:
            ping = role.mention
            break
    await target.send(content=ping or None, embed=embed, view=SessionView())
    if target != ctx.channel:
        await ctx.send(f"✅ Posted in {target.mention}", delete_after=8)


@bot.command(name="startup")
@staff_only()
async def startup(ctx: commands.Context, *, notes: str = "") -> None:
    """-startup [notes] — announce a session startup in #startup."""
    embed = base_embed(
        "🟢 Session Startup — SCRS",
        COLOUR_OK,
        "A Sunshine Coast roleplay session is **starting now**! Get set up and join up.",
    )
    embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    embed.add_field(name="Status", value="🟢 Starting", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    embed.add_field(
        name="How to join",
        value="Run `-setup` knowledge: check #information for the join steps, be in uniform / correct vehicle class, and click **I'm joining** below.",
        inline=False,
    )
    await _post_session_embed(ctx, ["startup"], embed, ["Civilian", "Verified"])


@bot.command(name="ea")
@staff_only()
async def ea(ctx: commands.Context, *, notes: str = "") -> None:
    """-ea [notes] — announce an Early Access session in #early-access."""
    embed = base_embed(
        "🟣 Early Access Session — SCRS",
        COLOUR_EA,
        "An **Early Access** session is opening for Early Access members before the public release.",
    )
    embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    embed.add_field(name="Status", value="🟣 Early Access", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    embed.add_field(name="Next step", value="When the session opens to everyone, staff will run `-release`.", inline=False)
    await _post_session_embed(ctx, ["early-access"], embed, ["Early Access", "Civilian"])


@bot.command(name="release")
@staff_only()
async def release(ctx: commands.Context, *, notes: str = "") -> None:
    """-release [notes] — release the session to the public."""
    embed = base_embed(
        "🔓 Session Released — Open to Everyone",
        COLOUR_INFO,
        "The session is now **released** — all Civilian players may join. Have a great roleplay!",
    )
    embed.add_field(name="Released by", value=ctx.author.mention, inline=True)
    embed.add_field(name="Status", value="🔓 Public", inline=True)
    if notes:
        embed.add_field(name="Details / Join Info", value=notes, inline=False)
    await _post_session_embed(ctx, ["early-access", "startup"], embed, ["Civilian", "Verified"])


@bot.command(name="setup")
@staff_only()
async def setup(ctx: commands.Context, *, join_code: str = "") -> None:
    """-setup [join code / info] — post the session setup embed."""
    embed = base_embed(
        "🧰 Session Setup — How to Join SCRS",
        COLOUR_STAFF,
        "Follow these steps to get into the session correctly:",
    )
    embed.add_field(name="1️⃣ Join", value=f"Use the join info: **{join_code}**" if join_code else "Use the join info posted in #startup.", inline=False)
    embed.add_field(name="2️⃣ Verify", value="Make sure you're verified (see #verify) so you have the Civilian role.", inline=False)
    embed.add_field(name="3️⃣ Get ready", value="Correct uniform / vehicle for your department or civilian role, and follow #rules at all times.", inline=False)
    embed.add_field(name="4️⃣ Need help?", value="Open a ticket with `-ticket` or ask in #support-channel.", inline=False)
    embed.add_field(name="Session Host", value=ctx.author.mention, inline=True)
    await ctx.send(embed=embed)


# --------------------------------------------------------------------------- #
# Civilian commands
# --------------------------------------------------------------------------- #


@bot.command(name="profile")
@civilian_only()
async def profile(ctx: commands.Context, member: discord.Member | None = None) -> None:
    """-profile [@user] — show profile, registration and tickets."""
    member = member or ctx.author
    infractions = store["infractions"].get(str(member.id), [])
    strikes = store["strikes"].get(str(member.id), [])
    ticket_count = store["tickets"].get(str(member.id), {}).get("count", 0)

    verified = has_any_role(member, {"Verified"})
    roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
    embed = base_embed(f"👤 Profile — {member.display_name}", COLOUR_MAIN)
    embed.set_thumbnail(url=member.display_avatar.url)
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
    embed.add_field(name="Tickets Opened", value=str(ticket_count), inline=True)
    embed.add_field(name="Infractions", value=str(len(infractions)), inline=True)
    embed.add_field(name="Staff Strikes", value=str(len(strikes)), inline=True)
    embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="ticket")
@civilian_only()
async def ticket(ctx: commands.Context, member: discord.Member | None = None, *, reason: str = "") -> None:
    """
    -ticket [reason]              -> open a ticket for yourself
    -ticket @user [reason]        -> open a ticket for that user
    """
    target = member or ctx.author
    guild = ctx.guild

    store["ticket_counter"] = store["ticket_counter"] + 1
    number = store["ticket_counter"]
    record = store["tickets"].setdefault(str(target.id), {"count": 0, "numbers": []})
    record["count"] += 1
    record["numbers"].append(number)
    save_store(store)

    category = find_category(guild, "ticket")
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        target: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for role_name in ("Staff Team", "High Rank", "Management", "Staff Manager", "Owner", "Co Owner", "Sigma Bot Crafter"):
        role = find_role(guild, role_name)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    safe_name = re.sub(r"[^a-z0-9-]", "", target.name.lower()) or "user"
    try:
        channel = await guild.create_text_channel(
            name=f"ticket-{safe_name}-{number}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket #{number} for {target} ({target.id}) — opened by {ctx.author}",
            reason=f"Ticket opened by {ctx.author} via -ticket",
        )
    except discord.Forbidden:
        await ctx.send(
            embed=base_embed(
                "❌ Can't create the ticket channel",
                COLOUR_ALERT,
                "The bot needs **Manage Channels** and its role must be high enough. A staff member can check the SCRS bot role.",
            )
        )
        return

    embed = base_embed(
        f"🎫 Ticket #{number}",
        COLOUR_INFO,
        f"Hi {target.mention} — staff will be with you shortly. Describe your issue below; a staff member can close this ticket with the button or `-close`.",
    )
    embed.add_field(name="Opened by", value=ctx.author.mention, inline=True)
    embed.add_field(name="For", value=target.mention, inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    await channel.send(content=f"{target.mention}", embed=embed, view=TicketCloseView(target.id))
    await log_to(
        guild,
        ["ticket-logs"],
        base_embed("🎫 Ticket Opened", COLOUR_INFO, f"Ticket #{number} for {target.mention}: {channel.mention}"),
    )
    await ctx.send(f"🎫 Ticket opened: {channel.mention}", delete_after=15)


@bot.command(name="close")
async def close(ctx: commands.Context) -> None:
    """-close — close the ticket channel you're in (owner or staff)."""
    if not ctx.channel.name.startswith("ticket-"):
        await ctx.send("This command only works inside a ticket channel.", delete_after=8)
        return
    is_owner = str(ctx.author.id) in (ctx.channel.topic or "")
    if is_owner or (isinstance(ctx.author, discord.Member) and passes(ctx.author, STAFF_ROLES)):
        await ctx.send("🔒 Closing this ticket in 3 seconds…")
        import asyncio

        await asyncio.sleep(3)
        await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")
    else:
        await ctx.send(embed=denied_embed("Staff Team"), delete_after=8)


@bot.command(name="911")
@civilian_only()
async def nine_one_one(ctx: commands.Context, *, call: str = "") -> None:
    """
    -911 <location> | <what's happening>
    Sends a 911 call to the #911 channel for Sheriff / Police / Fire.
    (Registered as "911" — type it exactly as -911.)
    """
    if "|" in call:
        location, situation = (part.strip() for part in call.split("|", 1))
    elif " - " in call:
        location, situation = (part.strip() for part in call.split(" - ", 1))
    else:
        location, situation = "Not specified", call.strip()
    if not situation:
        situation = "No details provided"

    embed = base_embed("🚨 911 CALL — Emergency Services Needed", COLOUR_ALERT)
    embed.add_field(name="Caller", value=f"{ctx.author.mention} ({ctx.author.display_name})", inline=False)
    embed.add_field(name="Location", value=location or "Not specified", inline=False)
    embed.add_field(name="Situation", value=situation, inline=False)
    embed.add_field(
        name="Services Requested",
        value="⭐ Sheriff • 🚓 Police • 🚒 Fire Department",
        inline=False,
    )
    embed.add_field(name="Status", value="⏳ Awaiting a unit — press **Responding** below if you're en route.", inline=False)

    target = find_channel(ctx.guild, "911") or ctx.channel
    ping_role = find_role(ctx.guild, "Emergency Services")
    message = await target.send(
        content=ping_role.mention if ping_role else None, embed=embed, view=NineOneOneView()
    )
    if target != ctx.channel:
        await ctx.send(f"🚨 Your 911 call was sent to {target.mention} — help is on the way.", delete_after=12)


# discord.py command names can't be passed positionally above for digits-only
# in some versions via decorator name — "911" is fine as a string name.

# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not TOKEN:
        print(
            "[SCRS] ERROR: DISCORD_TOKEN is not set.\n"
            "  • On Katabump: add DISCORD_TOKEN in your server's startup / environment settings.\n"
            "  • Locally: copy .env.example to .env and paste the token there.",
            file=sys.stderr,
        )
        sys.exit(1)
    bot.run(TOKEN)
