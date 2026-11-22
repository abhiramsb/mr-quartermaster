"""Pure planning helpers for /setup migrate (no Discord calls, so they can be tested offline)."""
from __future__ import annotations

from typing import Iterable, Optional


def plan_migration(
    members: Iterable,
    *,
    recruit,
    club,
    captain_role,
    squad_role,
    captain_member=None,
    give_club_to_all: bool = True,
    old_role=None,
) -> dict:
    """Return {member: (roles_to_add, roles_to_remove)} for members who need a change.

    Everyone gets Recruit, and Football Club if give_club_to_all. captain_member also gets MRFC Captain and
    MRFC Squad (and Football Club). Nobody else gets Captain or Squad. old_role, if given, is removed.
    """
    plan = {}
    for member in members:
        if getattr(member, "bot", False):
            continue
        wanted = [recruit]
        if give_club_to_all:
            wanted.append(club)
        if captain_member is not None and member.id == captain_member.id:
            wanted += [captain_role, squad_role, club]
        add = [r for r in dict.fromkeys(wanted) if r not in member.roles]
        remove = [old_role] if old_role is not None and old_role in member.roles else []
        if add or remove:
            plan[member] = (add, remove)
    return plan


def mention_blocks(mentions: list[str], limit: int = 1800) -> list[str]:
    """Join mentions with spaces into messages that stay under Discord's length limit."""
    blocks, current = [], ""
    for mention in mentions:
        if current and len(current) + len(mention) + 1 > limit:
            blocks.append(current)
            current = ""
        current = f"{current} {mention}".strip()
    if current:
        blocks.append(current)
    return blocks


def announcement_members(plan: dict, captain_member: Optional[object]) -> tuple[list, list]:
    """(everyone migrated, those who joined the football club without being captain)."""
    everyone = list(plan)
    football = [m for m in everyone if captain_member is None or m.id != captain_member.id]
    return everyone, football
