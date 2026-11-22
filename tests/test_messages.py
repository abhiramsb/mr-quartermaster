"""Checks of the welcome / send-off pools, GIF handling and the stored custom lists."""
import os
import re
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qm.db import Settings  # noqa: E402
from qm.layout import ROLE_CLUB  # noqa: E402
from qm.messages import (  # noqa: E402
    GAME_MESSAGE_COOLDOWN, GAME_WELCOMES, KINDS, MAX_LINE_LENGTH, SEED_GIFS, cooldown_ok, get_items, gif_items, is_direct_image, pick_gif, pick_line, render, save_items,
    valid_gif_url,
)

FOOTBALL_WORDS = re.compile(
    r"football|soccer|match|fixture|pitch|goal|squad|mrfc|gaffer|transfer|team sheet|boots|shin|striker|kick-?off",
    re.IGNORECASE,
)
PLACEHOLDERS = {"user", "name", "server", "count", "picker", "sessions", "new"}


def make_bot():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    return SimpleNamespace(settings=Settings(path))


def test_server_wide_pools_have_no_football_terms():
    for kind in ("welcome", "farewell", "greet"):
        for line in KINDS[kind].builtin:
            assert not FOOTBALL_WORDS.search(line), (kind, line)


def test_football_pool_is_football_and_mentions_the_user():
    for line in KINDS["football"].builtin:
        assert "{user}" in line, line


def test_football_leave_lines_use_the_name_not_a_mention():
    for line in KINDS["football_leave"].builtin:
        assert "{name}" in line and "{user}" not in line, line


def test_no_line_mentions_a_hidden_channel():
    # Welcomes are public; channel mentions would show as unknown to people who can't see that channel.
    for kind in KINDS.values():
        for line in kind.builtin:
            assert "{sessions}" not in line and "{picker}" not in line, line


def test_all_welcomes_post_in_reception():
    for welcome in GAME_WELCOMES.values():
        assert welcome.channel_key == "reception"
        assert welcome.leave_kind in KINDS


def test_all_lines_are_sane():
    for kind in KINDS.values():
        assert len(kind.builtin) >= 10, kind.key
        assert len(set(kind.builtin)) == len(kind.builtin), kind.key
        for line in kind.builtin:
            assert 0 < len(line) <= MAX_LINE_LENGTH, line
            used = set(re.findall(r"\{(\w+)\}", line))
            assert used <= PLACEHOLDERS, (line, used - PLACEHOLDERS)


def test_welcome_lines_mention_the_user_and_farewell_lines_the_name():
    assert all("{user}" in line for line in KINDS["welcome"].builtin)
    assert all("{name}" in line for line in KINDS["farewell"].builtin)


def test_every_game_welcome_points_at_a_real_kind():
    for role, welcome in GAME_WELCOMES.items():
        assert welcome.kind in KINDS, role
    assert GAME_WELCOMES[ROLE_CLUB].kind == "football"


def test_render_placeholders():
    values = {"user": "<@1>", "name": "Sam", "server": "Millennial Regiment Gaming", "count": "24"}
    text = render("Hi {user} / {name} to {server} #{count} {unknown}", values)
    assert text == "Hi <@1> / Sam to Millennial Regiment Gaming #24 {unknown}"


def test_cooldown_stops_toggle_spam_but_not_later_picks():
    bot = make_bot()
    assert cooldown_ok(bot, 1, ROLE_CLUB, 7, 1000.0)
    assert not cooldown_ok(bot, 1, ROLE_CLUB, 7, 1000.0 + GAME_MESSAGE_COOLDOWN - 1)
    assert cooldown_ok(bot, 1, ROLE_CLUB, 7, 1000.0 + GAME_MESSAGE_COOLDOWN + 1)
    assert cooldown_ok(bot, 1, ROLE_CLUB, 8, 1000.0)   # another person is unaffected
    assert cooldown_ok(bot, 2, ROLE_CLUB, 7, 1000.0)   # another server is unaffected


def test_gif_url_rules():
    assert valid_gif_url("https://media.tenor.com/abc/welcome.gif")
    assert valid_gif_url("https://tenor.com/view/some-gif-123")
    assert not valid_gif_url("http://example.com/a.gif")
    assert not valid_gif_url("javascript:alert(1)")
    assert not valid_gif_url("https://")
    assert not valid_gif_url("https://example.com/a b.gif")
    assert not valid_gif_url("https://example.com/" + "a" * 600)
    assert is_direct_image("https://media.tenor.com/abc/welcome.GIF?x=1")
    assert not is_direct_image("https://tenor.com/view/some-gif-123")


def test_seed_file_is_valid_and_complete():
    assert set(SEED_GIFS) == set(KINDS) - {"greet"}  # greet reuses the welcome GIFs
    assert {k: len(v) for k, v in SEED_GIFS.items()} == {"welcome": 7, "farewell": 6, "football": 5, "football_leave": 4}
    everything = [u for urls in SEED_GIFS.values() for u in urls]
    assert len(everything) == len(set(everything))
    assert all(valid_gif_url(u) and u.startswith("https://tenor.com/view/") for u in everything)


def test_seed_fills_empty_lists_once_and_never_overwrites_admin_changes():
    bot = make_bot()
    first = gif_items(bot, 1, "welcome")
    assert first == SEED_GIFS["welcome"]
    assert pick_gif(bot, 1, "welcome") in first
    # admin removes everything: it must stay empty, not re-seed
    save_items(bot, 1, "gifs", "welcome", [])
    assert gif_items(bot, 1, "welcome") == []
    assert pick_gif(bot, 1, "welcome") is None
    # admin adds their own before the list was ever used: seed does not clobber it
    save_items(bot, 1, "gifs", "farewell", ["https://media.tenor.com/mine.gif"])
    assert gif_items(bot, 1, "farewell") == ["https://media.tenor.com/mine.gif"]
    # another server gets its own seeded copy
    assert gif_items(bot, 2, "welcome") == SEED_GIFS["welcome"]


def test_custom_lines_and_gifs_are_stored_per_server_and_picked():
    bot = make_bot()
    save_items(bot, 1, "gifs", "welcome", ["https://media.tenor.com/a.gif"])
    assert pick_gif(bot, 1, "welcome") == "https://media.tenor.com/a.gif"
    save_items(bot, 1, "lines", "welcome", ["Custom line for {user}"])
    seen = {pick_line(bot, 1, "welcome") for _ in range(400)}
    assert "Custom line for {user}" in seen
    assert seen & set(KINDS["welcome"].builtin)
    assert get_items(bot, 1, "lines", "farewell") == []


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


def test_greet_pool_names_greeter_and_newcomer_and_has_gifs():
    for line in KINDS["greet"].builtin:
        assert "{user}" in line or "{new}" in line, line
    assert gif_items(make_bot(), 1, "greet") == SEED_GIFS["welcome"]
