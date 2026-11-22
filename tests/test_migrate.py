"""Checks of the migration plan: the owner becomes Captain, everyone else gets Recruit and Football Club only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qm.migrate import announcement_members, mention_blocks, plan_migration  # noqa: E402


class Role:
    def __init__(self, name):
        self.name = name


class Member:
    def __init__(self, uid, roles=(), bot=False):
        self.id, self.roles, self.bot = uid, list(roles), bot


RECRUIT, CLUB, CAPTAIN, SQUAD, OLD = (Role(n) for n in ("Recruit", "Football Club", "MRFC Captain", "MRFC Squad", "Old"))


def plan(members, **kw):
    return plan_migration(members, recruit=RECRUIT, club=CLUB, captain_role=CAPTAIN, squad_role=SQUAD, **kw)


def test_owner_is_captain_and_everyone_else_is_football_club_only():
    owner, a, b = Member(1), Member(2), Member(3)
    result = plan([owner, a, b], captain_member=owner)
    assert set(result[owner][0]) == {RECRUIT, CLUB, CAPTAIN, SQUAD}
    for m in (a, b):
        assert result[m][0] == [RECRUIT, CLUB]
        assert CAPTAIN not in result[m][0] and SQUAD not in result[m][0]


def test_bots_are_skipped_and_nothing_is_added_twice():
    bot = Member(9, bot=True)
    done = Member(2, roles=[RECRUIT, CLUB])
    partial = Member(3, roles=[RECRUIT])
    result = plan([bot, done, partial], captain_member=None)
    assert bot not in result and done not in result
    assert result[partial][0] == [CLUB]


def test_football_club_can_be_switched_off():
    a = Member(2)
    assert plan([a], captain_member=None, give_club_to_all=False)[a][0] == [RECRUIT]


def test_old_role_is_removed_only_from_those_who_have_it():
    has, hasnt = Member(2, roles=[OLD]), Member(3)
    result = plan([has, hasnt], captain_member=None, old_role=OLD)
    assert result[has][1] == [OLD]
    assert result[hasnt][1] == []


def test_announcement_lists_exclude_the_captain_from_the_football_welcome():
    owner, a, b = Member(1), Member(2), Member(3)
    result = plan([owner, a, b], captain_member=owner)
    everyone, football = announcement_members(result, owner)
    assert everyone == [owner, a, b]
    assert football == [a, b]


def test_mention_blocks_stay_under_the_limit():
    mentions = [f"<@{i}>" + "x" * 15 for i in range(200)]
    blocks = mention_blocks(mentions, limit=500)
    assert all(len(b) <= 500 for b in blocks)
    assert " ".join(blocks).split(" ") == mentions
    assert mention_blocks([]) == []


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
