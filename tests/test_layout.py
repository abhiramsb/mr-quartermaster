"""Offline checks of the layout and of who can see/post where. Run: python -m pytest -q  (or python tests/test_layout.py)."""
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402

from qm.layout import (  # noqa: E402
    EVERYONE, LAYOUT, ROLE_ADMIN, ROLE_CAPTAIN, ROLE_CLUB, ROLE_MOD, ROLE_RECRUIT, ROLE_SPECS, ROLE_SQUAD,
    build_overwrites, merged_access,
)

ROLE_NAMES = {s.name for s in ROLE_SPECS}
class Target:
    """Stands in for a Discord role or member (hashable, like the real ones)."""

    def __init__(self, name):
        self.name = name


TARGETS = {name: Target(name) for name in [EVERYONE, *ROLE_NAMES]}


def _channels():
    for cat in LAYOUT:
        for ch in cat.channels:
            yield cat, ch


def effective(perm: str, held_roles: list[str], cat, ch) -> bool:
    """Discord's permission rules: @everyone overwrite first, then the member's roles (allows beat denies)."""
    overwrites = build_overwrites(merged_access(cat, ch), TARGETS, ch.kind)
    value = True  # server default for @everyone on these permissions
    ev = overwrites.get(TARGETS[EVERYONE])
    if ev is not None:
        allow, deny = ev.pair()
        if getattr(deny, perm):
            value = False
        if getattr(allow, perm):
            value = True
    allow_any = deny_any = False
    for role in held_roles:
        ow = overwrites.get(TARGETS[role])
        if ow is None:
            continue
        allow, deny = ow.pair()
        allow_any |= getattr(allow, perm)
        deny_any |= getattr(deny, perm)
    if deny_any:
        value = False
    if allow_any:
        value = True
    return value


def can_view(held, cat, ch):
    return effective("view_channel", held, cat, ch)


def can_post(held, cat, ch):
    if ch.kind == "voice":
        return can_view(held, cat, ch) and effective("connect", held, cat, ch)
    return can_view(held, cat, ch) and effective("send_messages", held, cat, ch)


def find(key):
    for cat, ch in _channels():
        if ch.key == key:
            return cat, ch
    raise KeyError(key)


def test_category_order():
    assert [c.name for c in LAYOUT] == ["HQ", "MRFC", "GENERAL", "STAFF"]


def test_roles_referenced_exist():
    for cat in LAYOUT:
        for name in cat.access:
            assert name == EVERYONE or name in ROLE_NAMES, name
        for ch in cat.channels:
            for name in ch.access:
                assert name == EVERYONE or name in ROLE_NAMES, name


def test_channel_keys_and_names_unique_and_valid():
    keys = [ch.key for _, ch in _channels()]
    assert len(keys) == len(set(keys))
    for cat in LAYOUT:
        names = [c.name.lower() for c in cat.channels]
        assert len(names) == len(set(names)), cat.name
        for c in cat.channels:
            assert 1 <= len(c.name) <= 100
            if c.kind == "text":
                assert re.fullmatch(r"[a-z0-9-]+", c.name), c.name


def test_everyone_new_arrival_sees_only_reception():
    for cat, ch in _channels():
        visible = can_view([], cat, ch)
        assert visible == (cat.name == "HQ"), (cat.name, ch.name)
    for key in ("reception", "rules", "announcements", "pick_roles"):
        cat, ch = find(key)
        assert not can_post([], cat, ch), key


def test_recruit_gets_general_but_not_mrfc_or_staff():
    for cat, ch in _channels():
        if cat.name == "GENERAL":
            assert can_post([ROLE_RECRUIT], cat, ch), ch.name
        if cat.name in ("MRFC", "STAFF"):
            assert not can_view([ROLE_RECRUIT], cat, ch), ch.name


def test_football_club_member_access():
    club = [ROLE_RECRUIT, ROLE_CLUB]
    for key in ("mrfc_announcements", "mrfc_sessions", "mrfc_chat", "mrfc_lobby"):
        cat, ch = find(key)
        assert can_view(club, cat, ch), key
    assert can_post(club, *find("mrfc_chat"))
    assert can_post(club, *find("mrfc_lobby"))
    assert not can_post(club, *find("mrfc_announcements"))
    assert not can_post(club, *find("mrfc_sessions"))
    for key in ("mrfc_tactics", "mrfc_scouting", "mrfc_captains", "mrfc_captains_room"):
        assert not can_view(club, *find(key)), key


def test_squad_access():
    squad = [ROLE_RECRUIT, ROLE_CLUB, ROLE_SQUAD]  # /squad add also grants Football Club
    assert can_post(squad, *find("mrfc_tactics"))
    assert not can_view(squad, *find("mrfc_scouting"))
    assert not can_view(squad, *find("mrfc_captains"))
    assert not can_view(squad, *find("mrfc_captains_room"))
    assert not can_post(squad, *find("mrfc_sessions"))


def test_captain_access():
    captain = [ROLE_RECRUIT, ROLE_CLUB, ROLE_SQUAD, ROLE_CAPTAIN]
    for key in ("mrfc_announcements", "mrfc_chat", "mrfc_sessions", "mrfc_tactics", "mrfc_scouting",
                "mrfc_captains", "mrfc_lobby", "mrfc_captains_room"):
        assert can_post(captain, *find(key)), key


def test_staff_channels_only_for_staff():
    for cat, ch in _channels():
        if cat.name == "STAFF":
            assert can_post([ROLE_ADMIN], cat, ch)
            assert can_post([ROLE_MOD], cat, ch)
            assert not can_view([ROLE_CAPTAIN, ROLE_SQUAD, ROLE_CLUB, ROLE_RECRUIT], cat, ch)


def test_extra_members_always_get_rw():
    bot = Target("bot")
    cat, ch = find("mrfc_scouting")
    out = build_overwrites(merged_access(cat, ch), TARGETS, ch.kind, [bot])
    allow, _ = out[bot].pair()
    assert allow.view_channel and allow.send_messages and allow.read_message_history


def test_invite_permissions_integer():
    perms = discord.Permissions(
        view_channel=True, send_messages=True, embed_links=True, read_message_history=True,
        manage_roles=True, manage_channels=True, connect=True, speak=True,
    )
    assert perms.value == 271666192


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, repr(e))
    sys.exit(1 if failed else 0)


def test_streams_clips_is_general_and_renames_media():
    cat, ch = find("streams_clips")
    assert cat.name == "GENERAL"
    assert ch.name == "streams-n-clips" and ch.renamed_from == "media"
    assert can_post([ROLE_RECRUIT], cat, ch)
    assert not any(c.key == "mrfc_streams_clips" for _, c in _channels())
