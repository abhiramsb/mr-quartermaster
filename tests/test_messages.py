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
    GAME_WELCOMES, KINDS, MAX_LINE_LENGTH, get_items, is_direct_image, pick_gif, pick_line, render, save_items,
    valid_gif_url,
)

FOOTBALL_WORDS = re.compile(
    r"football|soccer|match|fixture|pitch|goal|squad|mrfc|gaffer|transfer|team sheet|boots|shin|striker|kick-?off",
    re.IGNORECASE,
)
PLACEHOLDERS = {"user", "name", "server", "count", "picker", "sessions"}


def make_bot():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    return SimpleNamespace(settings=Settings(path))


def test_server_wide_pools_have_no_football_terms():
    for kind in ("welcome", "farewell"):
        for line in KINDS[kind].builtin:
            assert not FOOTBALL_WORDS.search(line), (kind, line)


def test_football_pool_is_football_and_mentions_the_user():
    for line in KINDS["football"].builtin:
        assert "{user}" in line, line


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


def test_custom_lines_and_gifs_are_stored_per_server_and_picked():
    bot = make_bot()
    assert pick_gif(bot, 1, "welcome") is None  # no GIF until the admin adds one
    save_items(bot, 1, "gifs", "welcome", ["https://media.tenor.com/a.gif"])
    assert pick_gif(bot, 1, "welcome") == "https://media.tenor.com/a.gif"
    assert pick_gif(bot, 2, "welcome") is None  # another server is unaffected
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
