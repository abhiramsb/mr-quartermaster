"""The server layout MR_Quartermaster builds: roles, categories, channels and who can see/post where.

This module is plain data plus one pure helper (build_overwrites), so it can be tested without Discord.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import discord

EVERYONE = "@everyone"

ROLE_ADMIN = "Admin"
ROLE_MOD = "Mod"
ROLE_CAPTAIN = "MRFC Captain"
ROLE_SQUAD = "MRFC Squad"
ROLE_CLUB = "Football Club"
ROLE_RECRUIT = "Recruit"
ROLE_EVENTS = "Event Pings"
ROLE_NEWS = "News Pings"
ROLE_STREAMS = "Stream Pings"

# Access levels used in the layout below.
RW = "rw"      # see, read history, post (voice: connect and speak)
R = "r"        # see and read only
HIDE = "hide"  # channel is invisible


@dataclass(frozen=True)
class RoleSpec:
    name: str
    color: int = 0
    hoist: bool = False
    mentionable: bool = False
    # managed=False: created if missing, but never repositioned (Admin/Mod sit above the bot's role,
    # which a bot cannot arrange by itself).
    managed: bool = True


# Top to bottom. Managed roles are placed directly under the bot's own role, in this order.
ROLE_SPECS: tuple[RoleSpec, ...] = (
    RoleSpec(ROLE_ADMIN, 0xE74C3C, hoist=True, managed=False),
    RoleSpec(ROLE_MOD, 0xE67E22, hoist=True, managed=False),
    RoleSpec(ROLE_CAPTAIN, 0xF1C40F, hoist=True),
    RoleSpec(ROLE_SQUAD, 0x2ECC71, hoist=True),
    RoleSpec(ROLE_CLUB, 0x3498DB),
    RoleSpec(ROLE_RECRUIT, 0x95A5A6),
    RoleSpec(ROLE_EVENTS, 0x9B59B6, mentionable=True),
    RoleSpec(ROLE_NEWS, 0x1ABC9C, mentionable=True),
    RoleSpec(ROLE_STREAMS, 0xE91E63, mentionable=True),
)


@dataclass(frozen=True)
class ChannelSpec:
    key: str                      # settings key, e.g. "reception"
    name: str
    kind: str = "text"            # "text" or "voice"
    topic: str = ""
    access: Mapping[str, str] = field(default_factory=dict)  # overrides on top of the category's
    bot_env: str = ""             # env var holding another bot's user ID that must be able to post here
    renamed_from: tuple[str, ...] = ()  # older names; a channel found under one is renamed (and moved) instead of duplicated


@dataclass(frozen=True)
class CategorySpec:
    name: str
    access: Mapping[str, str]
    channels: tuple[ChannelSpec, ...]


_STAFF = {ROLE_ADMIN: RW, ROLE_MOD: RW}

LAYOUT: tuple[CategorySpec, ...] = (
    CategorySpec(
        "HQ",
        {EVERYONE: R, **_STAFF},
        (
            ChannelSpec("reception", "reception", topic="Say hi to new members. Joins and leaves show up here.",
                        access={EVERYONE: RW}, renamed_from=("the-reception",)),
            ChannelSpec("rules", "rules", topic="Server rules."),
            ChannelSpec("announcements", "announcements", topic="Server-wide news.", access={ROLE_ADMIN: RW, ROLE_MOD: RW}),
            ChannelSpec("pick_roles", "pick-your-roles", topic="Choose your game and ping roles.",
                        renamed_from=("get-roles",)),
        ),
    ),
    CategorySpec(
        "MRFC",
        {EVERYONE: HIDE, ROLE_CLUB: R, ROLE_SQUAD: R, ROLE_CAPTAIN: R, **_STAFF},
        (
            ChannelSpec("mrfc_announcements", "mrfc-announcements", topic="MRFC news from the Captains.",
                        access={ROLE_CAPTAIN: RW}),
            ChannelSpec("mrfc_chat", "mrfc-chat", topic="Football chat.",
                        access={ROLE_CLUB: RW, ROLE_SQUAD: RW, ROLE_CAPTAIN: RW}),
            ChannelSpec("mrfc_sessions", "mrfc-sessions", topic="Session RSVPs from MRFC_GroundsKeeper.",
                        access={ROLE_CAPTAIN: RW}, bot_env="GROUNDSKEEPER_BOT_ID", renamed_from=("sessions",)),
            ChannelSpec("mrfc_tactics", "mrfc-tactics", topic="Squad tactics and the coach's daily debrief.",
                        access={ROLE_CLUB: HIDE, ROLE_SQUAD: RW, ROLE_CAPTAIN: RW}, bot_env="COACH_BOT_ID",
                        renamed_from=("tactics",)),
            ChannelSpec("mrfc_scouting", "mrfc-scouting", topic="Recruiting finds from MRFC_Scout.",
                        access={ROLE_CLUB: HIDE, ROLE_SQUAD: HIDE, ROLE_CAPTAIN: RW}, bot_env="SCOUT_BOT_ID",
                        renamed_from=("scouting",)),
            ChannelSpec("mrfc_captains", "mrfc-captains", topic="Captains only.",
                        access={ROLE_CLUB: HIDE, ROLE_SQUAD: HIDE, ROLE_CAPTAIN: RW},
                        renamed_from=("captains-corner",)),
            ChannelSpec("mrfc_lobby", "MRFC Lobby", kind="voice",
                        access={ROLE_CLUB: RW, ROLE_SQUAD: RW, ROLE_CAPTAIN: RW}, renamed_from=("Lobby",)),
            ChannelSpec("mrfc_captains_room", "Captains' Room", kind="voice",
                        access={ROLE_CLUB: HIDE, ROLE_SQUAD: HIDE, ROLE_CAPTAIN: RW}),
        ),
    ),
    CategorySpec(
        "THE BARRACKS",
        {EVERYONE: HIDE, ROLE_RECRUIT: RW, **_STAFF},
        (
            ChannelSpec("general", "general", topic="Main chat."),
            ChannelSpec("streams_clips", "streams-n-clips", topic="Live alerts, clips, screenshots and highlights.",
                        renamed_from=("media",)),
            ChannelSpec("lfg", "looking-for-group", topic="Find people to play any game with."),
            ChannelSpec("off_topic", "off-topic"),
            ChannelSpec("lounge1", "General Lounge", kind="voice", renamed_from=("Timepass",)),
            ChannelSpec("lounge2", "Lounge 2", kind="voice"),
        ),
    ),
    CategorySpec(
        "STAFF",
        {EVERYONE: HIDE, **_STAFF},
        (
            ChannelSpec("staff_chat", "staff-chat"),
            ChannelSpec("bot_logs", "bot-logs", topic="Joins, leaves, role changes and squad changes."),
            ChannelSpec("bot_commands", "bot-commands"),
        ),
    ),
)


def overwrite_for(level: str, kind: str) -> discord.PermissionOverwrite:
    """Translate an access level into a Discord permission overwrite.

    Allows are limited to permissions a bot normally holds (view, send, history, connect, speak) because
    Discord refuses overwrites that grant something the bot itself lacks.
    """
    if level == HIDE:
        return discord.PermissionOverwrite(view_channel=False)
    if kind == "voice":
        if level == RW:
            return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        return discord.PermissionOverwrite(view_channel=True, connect=False)
    if level == RW:
        return discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True)
    return discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=False,
        send_messages_in_threads=False,
        create_public_threads=False,
        create_private_threads=False,
    )


def merged_access(category: CategorySpec, channel: ChannelSpec | None = None) -> dict[str, str]:
    access = dict(category.access)
    if channel is not None:
        access.update(channel.access)
    return access


def build_overwrites(
    access: Mapping[str, str],
    targets: Mapping[str, object | None],
    kind: str = "text",
    extra_rw: Iterable[object] = (),
) -> dict:
    """Return {role_or_member: PermissionOverwrite}.

    targets maps a role name (and EVERYONE) to the role object; names whose role is None are skipped.
    extra_rw are members (the bot itself, other bots) that must always be able to post.
    """
    out: dict = {}
    for name, level in access.items():
        target = targets.get(name)
        if target is not None:
            out[target] = overwrite_for(level, kind)
    for member in extra_rw:
        if member is not None:
            out[member] = overwrite_for(RW, kind)
    return out
