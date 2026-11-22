"""Shared helpers: finding configured roles/channels, staff checks, and the bot-logs channel."""
from __future__ import annotations

import re
from typing import Optional

import discord

from .layout import ROLE_ADMIN, ROLE_CAPTAIN, ROLE_MOD


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def get_role(bot, guild: discord.Guild, name: str) -> Optional[discord.Role]:
    """Role stored by /setup (survives renames), falling back to a lookup by name."""
    rid = bot.settings.get_int(guild.id, f"role:{slug(name)}")
    role = guild.get_role(rid) if rid else None
    return role or discord.utils.get(guild.roles, name=name)


def get_channel(bot, guild: discord.Guild, key: str):
    cid = bot.settings.get_int(guild.id, f"channel:{key}")
    return guild.get_channel(cid) if cid else None


def has_role(bot, member: discord.abc.User, role_name: str) -> bool:
    guild = getattr(member, "guild", None)
    if guild is None:
        return False
    role = get_role(bot, guild, role_name)
    return role is not None and role in getattr(member, "roles", [])


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


def is_staff(bot, member: discord.Member) -> bool:
    """Administrators, Manage Server holders, and members with the Admin or Mod role."""
    perms = member.guild_permissions
    return (
        perms.administrator
        or perms.manage_guild
        or has_role(bot, member, ROLE_ADMIN)
        or has_role(bot, member, ROLE_MOD)
    )


def is_captain(bot, member: discord.Member) -> bool:
    return is_admin(member) or has_role(bot, member, ROLE_CAPTAIN)


async def send_log(bot, guild: discord.Guild, content: Optional[str] = None, embed: Optional[discord.Embed] = None):
    channel = get_channel(bot, guild, "bot_logs")
    if channel is None:
        return
    try:
        await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


def chunk_lines(lines: list[str], limit: int = 1800) -> list[str]:
    """Join lines into messages that stay under Discord's length limit."""
    chunks, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    return chunks
