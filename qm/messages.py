"""Random welcome / send-off lines and curated GIFs.

Three kinds of message exist today:
  welcome   server-wide, no football words (posted in #reception when someone joins)
  farewell  server-wide (posted in #reception when someone leaves)
  football        posted in #reception when someone picks the Football Club role
  football_leave  posted in #reception when someone deselects it

To add a game later: add a MessageKind with its built-in lines, then a GameWelcome that says which role
triggers it and which channel it posts in.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import discord

from .layout import ROLE_CLUB
from .util import get_channel, slug

MAX_LINE_LENGTH = 300
MAX_CUSTOM_ITEMS = 50
IMAGE_EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")

# Placeholders: {user} mention, {name} display name, {server}, {count}, {picker} and {sessions} channel mentions.
WELCOME_LINES = (
    "{user} has reported for duty. Fall in, Recruit!",
    "A wild {user} appeared. It's super effective!",
    "{user} just spawned in. Please stay seated until the loading screen finishes.",
    "Roll call: {user} is present. We're now {count} strong.",
    "{user} joined the party. Loot is shared equally. Mostly.",
    "Welcome, {user}. Your training starts now. Snacks are optional.",
    "{user} has entered the lobby. Ready check in progress...",
    "Achievement unlocked: {user} joined {server}.",
    "Heads up, Regiment! {user} has joined the ranks.",
    "{user} pressed Join Server without hesitation. Respect.",
    "New challenger approaching: {user}. Play nice.",
    "{user} has arrived. Somebody tell them where the good snacks are.",
    "Welcome to {server}, {user}. Please don't feed the lag.",
    "Reinforcements have arrived! Say hello to {user}.",
    "{user} dropped in with no fall damage. Impressive.",
)

FAREWELL_LINES = (
    "{name} has left the server. Pour one out for their inventory.",
    "{name} disconnected. Their last words: \"brb\".",
    "{name} has been discharged with honours. We're now {count} strong.",
    "{name} rage-quit reality... and the server. Safe travels!",
    "{name} left the lobby. The queue moves on.",
    "Another one bites the dust. See you around, {name}!",
    "{name} has gone AFK permanently. The Regiment salutes you.",
    "{name} logged off for the last time. GG, no re.",
    "{name} left the party. The party is now {count} strong.",
    "{name} took the portal home. The door's always open.",
    "{name} has respawned somewhere else. Good luck out there!",
    "Farewell, {name}. May your ping be low and your loot be high.",
)

FOOTBALL_LINES = (
    "{user} has joined the football club! Matches are scheduled in the MRFC section.",
    "New signing! {user} is officially on the team sheet. Welcome to MRFC.",
    "{user} has arrived at the training ground. Boots on, shin pads optional.",
    "The transfer window is open and {user} just walked in. Welcome to MRFC!",
    "{user} wants a game. Grab a position and get on the team sheet.",
    "Welcome to MRFC, {user}! First rule of match day: call for the ball.",
    "{user} has signed on the dotted line. Say hello in the chat!",
    "A new face in the dressing room: {user}. Welcome to MRFC.",
    "{user}, welcome to MRFC. Your debut could be this week.",
    "Fresh legs! {user} joins MRFC. The gaffer approves.",
    "Match day just got better: {user} is now part of MRFC.",
    "{user} has been spotted in the tunnel. Welcome to the club!",
)


_FOOTBALL_EMOJI = ("⚽", "🏟️", "🧤", "🥅", "🏆", "👟")
FOOTBALL_LINES = tuple(f"{_FOOTBALL_EMOJI[i % len(_FOOTBALL_EMOJI)]} {line}" for i, line in enumerate(FOOTBALL_LINES))

FOOTBALL_LEAVE_LINES = (
    "👟 {name} has hung up their boots at MRFC. Thanks for the games!",
    "🚪 {name} left the football club. The dressing room door stays open.",
    "🔄 Substitution: {name} is off. Thanks for everything on the pitch!",
    "📋 {name} has left MRFC and headed for the transfer list.",
    "⏱️ Full time for {name} at MRFC. Come back for the next season!",
    "🧥 {name} left the training ground. We'll keep your shirt warm.",
    "🟥 Red card? No, {name} just left on their own. See you around!",
    "🪑 {name} is on the bench of life now. Thanks for playing with MRFC!",
    "🤝 {name} has stepped away from MRFC. Good luck out there!",
    "📣 The gaffer says thanks for the effort, {name}. The door's open.",
)


@dataclass(frozen=True)
class MessageKind:
    key: str
    label: str
    builtin: tuple[str, ...]


KINDS: dict[str, MessageKind] = {
    "welcome": MessageKind("welcome", "Welcome (server-wide)", WELCOME_LINES),
    "farewell": MessageKind("farewell", "Send-off (server-wide)", FAREWELL_LINES),
    "football": MessageKind("football", "Football welcome (after picking Football Club)", FOOTBALL_LINES),
    "football_leave": MessageKind("football_leave", "Football send-off (after deselecting Football Club)", FOOTBALL_LEAVE_LINES),
}


@dataclass(frozen=True)
class GameWelcome:
    kind: str          # key in KINDS, used when the role is picked
    leave_kind: str    # key in KINDS, used when the role is deselected
    channel_key: str   # settings key of the channel to post in
    title: str
    leave_title: str
    colour: int
    leave_colour: int


# Role picked -> the welcome that follows. Add future games here.
GAME_WELCOMES: dict[str, GameWelcome] = {
    ROLE_CLUB: GameWelcome(
        "football", "football_leave", "reception",
        "⚽ New signing!", "🟥 Hanging up the boots",
        0x2ECC71, 0xE74C3C,
    ),
}


# ---- curated lists stored per server (extra lines and GIF links added by admins) ----

def get_items(bot, guild_id: int, store: str, kind: str) -> list[str]:
    raw = bot.settings.get(guild_id, f"{store}:{kind}")
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [x for x in data if isinstance(x, str)]


def save_items(bot, guild_id: int, store: str, kind: str, items: list[str]) -> None:
    bot.settings.set(guild_id, f"{store}:{kind}", json.dumps(items))


def pick_line(bot, guild_id: int, kind: str) -> str:
    pool = list(KINDS[kind].builtin) + get_items(bot, guild_id, "lines", kind)
    return random.choice(pool)


def _load_seed() -> dict[str, list[str]]:
    try:
        data = json.loads((Path(__file__).parent / "seed_gifs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: [u for u in v if isinstance(u, str)] for k, v in data.items() if isinstance(v, list)}


SEED_GIFS: dict[str, list[str]] = _load_seed()


def gif_items(bot, guild_id: int, kind: str) -> list[str]:
    """The GIF list for a kind. The first time a list is used it is filled from seed_gifs.json (only if empty,
    and only once), so GIFs an admin adds or removes later are never overwritten."""
    marker = f"gifs_seeded:{kind}"
    if not bot.settings.get(guild_id, marker):
        bot.settings.set(guild_id, marker, "1")
        if not get_items(bot, guild_id, "gifs", kind):
            save_items(bot, guild_id, "gifs", kind, list(SEED_GIFS.get(kind, [])))
    return get_items(bot, guild_id, "gifs", kind)


def pick_gif(bot, guild_id: int, kind: str) -> Optional[str]:
    gifs = gif_items(bot, guild_id, kind)
    return random.choice(gifs) if gifs else None


def valid_gif_url(url: str) -> bool:
    if len(url) > 500 or any(c.isspace() for c in url):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_direct_image(url: str) -> bool:
    return urlparse(url).path.lower().endswith(IMAGE_EXTENSIONS)


def render(template: str, values: dict[str, str]) -> str:
    """Replace known {placeholders}; anything else is left exactly as typed."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def values_for(bot, guild: discord.Guild, member: discord.abc.User) -> dict[str, str]:
    picker = get_channel(bot, guild, "pick_roles")
    sessions = get_channel(bot, guild, "mrfc_sessions")
    return {
        "user": member.mention,
        "name": member.display_name,
        "server": guild.name,
        "count": str(guild.member_count or 0),
        "picker": picker.mention if picker else "#pick-your-roles",
        "sessions": sessions.mention if sessions else "#mrfc-sessions",
    }


async def send_embed(channel: discord.abc.Messageable, embed: discord.Embed, gif: Optional[str],
                     mentions: discord.AllowedMentions) -> None:
    """Send the embed. A direct image/GIF link goes inside it; any other link (Tenor or Giphy page)
    follows as its own message so Discord shows it as an animation."""
    link_only: Optional[str] = None
    if gif:
        if is_direct_image(gif):
            embed.set_image(url=gif)
        else:
            link_only = gif
    await channel.send(embed=embed, allowed_mentions=mentions)
    if link_only:
        await channel.send(link_only, allowed_mentions=discord.AllowedMentions.none())


GAME_MESSAGE_COOLDOWN = 300  # seconds; stops message spam when someone toggles a role back and forth


def cooldown_ok(bot, guild_id: int, role_name: str, user_id: int, now: float) -> bool:
    """True if this person may trigger a game message now. Records the time when it returns True."""
    key = f"gamemsg:{slug(role_name)}:{user_id}"
    last = bot.settings.get(guild_id, key)
    try:
        if last is not None and now - float(last) < GAME_MESSAGE_COOLDOWN:
            return False
    except ValueError:
        pass
    bot.settings.set(guild_id, key, repr(now))
    return True


async def _game_message(bot, guild: discord.Guild, member: discord.Member, role_name: str, *, joining: bool) -> None:
    game = GAME_WELCOMES.get(role_name)
    if game is None:
        return
    channel = get_channel(bot, guild, game.channel_key)
    if channel is None:
        return
    if not cooldown_ok(bot, guild.id, role_name, member.id, time.time()):
        return
    kind = game.kind if joining else game.leave_kind
    line = render(pick_line(bot, guild.id, kind), values_for(bot, guild, member))
    embed = discord.Embed(
        title=game.title if joining else game.leave_title,
        description=line,
        colour=discord.Colour(game.colour if joining else game.leave_colour),
    )
    if joining:
        embed.set_thumbnail(url=member.display_avatar.url)
    mentions = discord.AllowedMentions(users=[member]) if joining else discord.AllowedMentions.none()
    try:
        await send_embed(channel, embed, pick_gif(bot, guild.id, kind), mentions)
    except discord.HTTPException:
        pass


async def game_welcome(bot, guild: discord.Guild, member: discord.Member, role_name: str) -> None:
    """Posted in the game's channel after someone picks a game role."""
    await _game_message(bot, guild, member, role_name, joining=True)


async def game_leave(bot, guild: discord.Guild, member: discord.Member, role_name: str) -> None:
    """Posted in the game's channel after someone deselects a game role."""
    await _game_message(bot, guild, member, role_name, joining=False)
