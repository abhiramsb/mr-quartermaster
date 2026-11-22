"""Builds (or updates) the server layout from layout.py. Safe to run again; dry_run changes nothing."""
from __future__ import annotations

import os
from typing import Optional

import discord

from .layout import (
    EVERYONE,
    LAYOUT,
    ROLE_SPECS,
    build_overwrites,
    merged_access,
)
from .util import slug

REASON = "MR_Quartermaster /setup"


async def ensure_roles(bot, guild: discord.Guild, dry_run: bool, log: list[str]) -> dict[str, Optional[discord.Role]]:
    roles: dict[str, Optional[discord.Role]] = {EVERYONE: guild.default_role}
    for spec in ROLE_SPECS:
        role = discord.utils.get(guild.roles, name=spec.name)
        if role is None:
            log.append(f"➕ create role **{spec.name}**")
            if not dry_run:
                role = await guild.create_role(
                    name=spec.name,
                    colour=discord.Colour(spec.color),
                    hoist=spec.hoist,
                    mentionable=spec.mentionable,
                    reason=REASON,
                )
        else:
            log.append(f"✔ role **{spec.name}** already exists")
        roles[spec.name] = role
        if role is not None:
            bot.settings.set(guild.id, f"role:{slug(spec.name)}", role.id)
    return roles


async def reorder_roles(guild: discord.Guild, roles: dict[str, Optional[discord.Role]], dry_run: bool, log: list[str]) -> None:
    """Place the managed roles directly under the bot's top role, in layout order."""
    if dry_run:
        log.append("↕ would place Captain, Squad, Football Club, Recruit and the ping roles under my role")
        return
    top = guild.me.top_role
    managed = [roles[s.name] for s in ROLE_SPECS if s.managed and roles.get(s.name) is not None]
    movable = [r for r in managed if r < top]
    for r in managed:
        if r not in movable:
            log.append(f"⚠ **{r.name}** is above my role, so I can't move it. Move my role to the top, under Admin, and run /setup again.")
    if not movable:
        return
    if top.position - len(movable) < 1:
        log.append("⚠ My role is too low in the role list to arrange the others. Move it up and run /setup again.")
        return
    positions = {role: top.position - 1 - i for i, role in enumerate(movable)}
    await guild.edit_role_positions(positions=positions, reason=REASON)
    log.append("↕ arranged the MRFC, Recruit and ping roles under my role")


def _bot_member(guild: discord.Guild, env_name: str) -> Optional[discord.Member]:
    raw = os.getenv(env_name, "").strip()
    if not raw.isdigit():
        return None
    return guild.get_member(int(raw))


async def ensure_layout(bot, guild: discord.Guild, roles: dict[str, Optional[discord.Role]], dry_run: bool, log: list[str]) -> None:
    for cat_spec in LAYOUT:
        base_extra = [guild.me]
        cat_overwrites = build_overwrites(merged_access(cat_spec), roles, "text", base_extra)
        category = discord.utils.find(lambda c: c.name.lower() == cat_spec.name.lower(), guild.categories)
        if category is None:
            log.append(f"➕ create category **{cat_spec.name}**")
            if not dry_run:
                category = await guild.create_category(cat_spec.name, overwrites=cat_overwrites, reason=REASON)
        else:
            others = [c for c in category.channels if c.name.lower() not in {s.name.lower() for s in cat_spec.channels}]
            note = f" (it also holds {len(others)} channel(s) that aren't part of the layout)" if others else ""
            log.append(f"♻ category **{cat_spec.name}** exists, so I'll update its permissions{note}")
            if not dry_run:
                await category.edit(overwrites=cat_overwrites, reason=REASON)

        for ch_spec in cat_spec.channels:
            extra = [guild.me]
            if ch_spec.bot_env:
                other = _bot_member(guild, ch_spec.bot_env)
                if other is not None:
                    extra.append(other)
                elif os.getenv(ch_spec.bot_env, "").strip():
                    log.append(f"⚠ the bot set in {ch_spec.bot_env} isn't in this server yet, so #{ch_spec.name} won't include it")
                else:
                    log.append(f"ℹ {ch_spec.bot_env} isn't set, so give that bot access to #{ch_spec.name} yourself")
            overwrites = build_overwrites(merged_access(cat_spec, ch_spec), roles, ch_spec.kind, extra)
            channel_type = discord.ChannelType.voice if ch_spec.kind == "voice" else discord.ChannelType.text
            existing = None
            if category is not None:
                existing = discord.utils.find(
                    lambda c: c.name.lower() == ch_spec.name.lower() and c.type == channel_type, category.channels
                )
            if existing is None:
                log.append(f"➕ create #{ch_spec.name}")
                if dry_run or category is None:
                    continue
                if ch_spec.kind == "voice":
                    existing = await category.create_voice_channel(ch_spec.name, overwrites=overwrites, reason=REASON)
                else:
                    existing = await category.create_text_channel(
                        ch_spec.name, topic=ch_spec.topic or None, overwrites=overwrites, reason=REASON
                    )
            else:
                log.append(f"♻ #{ch_spec.name} exists, so I'll update its permissions")
                if not dry_run:
                    await existing.edit(overwrites=overwrites, reason=REASON)
            if existing is not None:
                bot.settings.set(guild.id, f"channel:{ch_spec.key}", existing.id)


async def build(bot, guild: discord.Guild, dry_run: bool) -> list[str]:
    log: list[str] = []
    roles = await ensure_roles(bot, guild, dry_run, log)
    await reorder_roles(guild, roles, dry_run, log)
    await ensure_layout(bot, guild, roles, dry_run, log)
    return log
