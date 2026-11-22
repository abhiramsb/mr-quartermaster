"""Random welcome / send-off lines and curated GIFs.

Three kinds of message exist today:
  welcome   server-wide, no football words (posted in #reception when someone joins)
  farewell  server-wide (posted in #reception when someone leaves)
  football  posted in #mrfc-chat the first time someone picks the Football Club role

To add a game later: add a MessageKind with its built-in lines, then a GameWelcome that says which role
triggers it and which channel it posts in.
"""
from __future__ import annotations

import json
import random
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
    "{user} has joined the football club! Check {sessions} for the next match.",
    "New signing! {user} is officially on the team sheet. Welcome to MRFC.",
    "{user} has arrived at the training ground. Boots on, shin pads optional.",
    "The transfer window is open and {user} just walked in. Welcome to MRFC!",
    "{user} wants a game. Fixtures live in {sessions}, so grab a position.",
    "Welcome to MRFC, {user}! First rule of match day: call for the ball.",
    "{user} has signed on the dotted line. Say hello in the chat!",
    "A new face in the dressing room: {user}. Welcome to MRFC.",
    "{user}, welcome to MRFC. Your debut could be in {sessions}.",
    "Fresh legs! {user} joins MRFC. The gaffer approves.",
    "Match day just got better: {user} is now part of MRFC.",
    "{user} has been spotted in the tunnel. Welcome to the club!",
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
}


@dataclass(frozen=True)
class GameWelcome:
    kind: str          # key in KINDS
    channel_key: str   # settings key of the channel to post in
    title: str


# Role picked -> the welcome that follows. Add future games here.
GAME_WELCOMES: dict[str, GameWelcome] = {
    ROLE_CLUB: GameWelcome("football", "mrfc_chat", "New signing!"),
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


def pick_gif(bot, guild_id: int, kind: str) -> Optional[str]:
    gifs = get_items(bot, guild_id, "gifs", kind)
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


async def game_welcome(bot, guild: discord.Guild, member: discord.Member, role_name: str) -> None:
    """The follow-up welcome after someone picks a game role. Sent once per person per game."""
    welcome = GAME_WELCOMES.get(role_name)
    if welcome is None:
        return
    channel = get_channel(bot, guild, welcome.channel_key)
    if channel is None:
        return
    marker = f"welcomed:{slug(role_name)}:{member.id}"
    if bot.settings.get(guild.id, marker):
        return
    bot.settings.set(guild.id, marker, "1")
    line = render(pick_line(bot, guild.id, welcome.kind), values_for(bot, guild, member))
    embed = discord.Embed(title=welcome.title, description=line, colour=discord.Colour.gold())
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await send_embed(channel, embed, pick_gif(bot, guild.id, welcome.kind),
                         discord.AllowedMentions(users=[member]))
    except discord.HTTPException:
        pass
