"""Stream alerts: link parsing, go-live logic, embeds and the two API clients (against a fake HTTP session)."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from qm.db import Settings  # noqa: E402
from qm.layout import ROLE_SPECS, ROLE_STREAMS  # noqa: E402
from qm.streams import (  # noqa: E402
    END_AFTER_MISSES, RESUME_WINDOW, TWITCH, YOUTUBE, LiveStream, StreamAPIError, TwitchClient, YouTubeClient,
    add_link, diff_live, ended_embed, link_key, live_embed, load_links, load_state, parse_twitch,
    parse_twitch_stream, parse_youtube, parse_youtube_video, remove_link, save_links, save_state,
)
from qm.views import PICKER_ROLES  # noqa: E402

UC = "UC" + "a" * 22


def twitch_stream(sid="s1", login="ace", title="Pro Clubs night"):
    return LiveStream(TWITCH, login, sid, title, "EA SPORTS FC 27", f"https://www.twitch.tv/{login}", "http://img", "Ace")


# ---- parsing -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Ace_99", "ace_99"), ("@ace", "ace"), ("twitch.tv/Ace", "ace"), ("https://www.twitch.tv/ace/", "ace"),
    ("https://twitch.tv/ace?sr=a", "ace"), ("a", None), ("has space", None), ("https://example.com/ace", None),
])
def test_parse_twitch(text, expected):
    assert parse_twitch(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("@ace", ("handle", "@ace")), ("ace", ("handle", "@ace")), ("https://www.youtube.com/@Ace", ("handle", "@Ace")),
    (UC, ("id", UC)), (f"youtube.com/channel/{UC}", ("id", UC)), (f"https://www.youtube.com/channel/{UC}/live", ("id", UC)),
    ("https://youtube.com/c/oldstyle", None), ("https://youtube.com/user/old", None), ("!!", None),
])
def test_parse_youtube(text, expected):
    assert parse_youtube(text) == expected


# ---- links and storage -------------------------------------------------------------------------------------

def test_add_replace_and_remove_links():
    links, other = add_link([], 1, TWITCH, "ace", "Ace", "")
    assert other is None and len(links) == 1
    links, _ = add_link(links, 1, TWITCH, "ace2", "Ace Two", "")          # replaces the member's Twitch link
    assert [l["channel_id"] for l in links] == ["ace2"]
    links, _ = add_link(links, 1, YOUTUBE, UC, "Ace YT", "FC 27")         # a different platform is kept alongside
    assert len(links) == 2
    same, other = add_link(links, 2, TWITCH, "ace2", "Ace Two", "")       # someone else can't take the same channel
    assert other == 1 and same == links
    links, removed = remove_link(links, 1, TWITCH)
    assert removed and len(links) == 1
    assert remove_link(links, 1, TWITCH)[1] is False


def test_store_roundtrip_and_bad_data():
    bot = Settings(os.path.join(tempfile.mkdtemp(), "t.db"))
    assert load_links(bot, 1) == [] and load_state(bot, 1) == {}
    save_links(bot, 1, [{"user_id": 5}])
    save_state(bot, 1, {"a": {"live": True}})
    assert load_links(bot, 1) == [{"user_id": 5}] and load_state(bot, 1) == {"a": {"live": True}}
    bot.set(1, "streams:links", "not json")
    bot.set(1, "streams:state", "[1]")
    assert load_links(bot, 1) == [] and load_state(bot, 1) == {}


# ---- who just went live ------------------------------------------------------------------------------------

def test_new_stream_is_announced_once():
    s = twitch_stream()
    state, actions = diff_live({}, {s.key: s}, {s.key}, 1000)
    assert actions == [("announce", s.key)]
    state[s.key]["message_id"] = 55
    state2, actions2 = diff_live(state, {s.key: s}, {s.key}, 1060)
    assert actions2 == [] and state2[s.key]["message_id"] == 55


def test_stream_ends_only_after_consecutive_misses():
    s = twitch_stream()
    state, _ = diff_live({}, {s.key: s}, {s.key}, 1000)
    state[s.key]["message_id"] = 55
    t = 1000
    for i in range(END_AFTER_MISSES - 1):
        t += 60
        state, actions = diff_live(state, {}, {s.key}, t)
        assert actions == []
    t += 60
    state, actions = diff_live(state, {}, {s.key}, t)
    assert actions == [("end", s.key)] and state[s.key]["live"] is False


def test_a_blip_does_not_end_the_stream():
    s = twitch_stream()
    state, _ = diff_live({}, {s.key: s}, {s.key}, 1000)
    state, a = diff_live(state, {}, {s.key}, 1060)            # one miss
    state, a2 = diff_live(state, {s.key: s}, {s.key}, 1120)   # back again
    assert a == [] and a2 == [] and state[s.key]["misses"] == 0


def test_api_outage_never_ends_or_reannounces():
    s = twitch_stream()
    state, _ = diff_live({}, {s.key: s}, {s.key}, 1000)
    for t in (1060, 1120, 1180, 1240):
        state, actions = diff_live(state, {}, set(), t)      # the platform wasn't polled at all
        assert actions == []
    assert state[s.key]["live"] is True


def test_quick_return_resumes_the_old_post_and_late_return_announces_again():
    s = twitch_stream("s1")
    state, _ = diff_live({}, {s.key: s}, {s.key}, 1000)
    state[s.key]["message_id"] = 55
    for t in (1060, 1120):
        state, actions = diff_live(state, {}, {s.key}, t)
    assert actions == [("end", s.key)]
    back = twitch_stream("s2")
    resumed, actions = diff_live(state, {back.key: back}, {back.key}, 1120 + 300)
    assert actions == [("resume", back.key)] and resumed[back.key]["message_id"] == 55
    later, actions = diff_live(state, {back.key: back}, {back.key}, 1120 + RESUME_WINDOW + 5)
    assert actions == [("announce", back.key)] and later[back.key]["message_id"] is None


def test_new_stream_id_while_live_is_a_new_announcement():
    a, b = twitch_stream("s1"), twitch_stream("s2")
    state, _ = diff_live({}, {a.key: a}, {a.key}, 1000)
    state, actions = diff_live(state, {b.key: b}, {b.key}, 1060)
    assert actions == [("announce", a.key)]


def test_removed_link_ends_its_stream():
    s = twitch_stream()
    state, _ = diff_live({}, {s.key: s}, {s.key}, 1000)
    # the cog adds keys with no link to `polled`, so they end after the usual misses
    for t in (1060, 1120):
        state, actions = diff_live(state, {}, {s.key}, t)
    assert actions == [("end", s.key)]


def test_old_ended_entries_are_forgotten():
    state = {"twitch:old": {"live": False, "ended_at": 0, "message_id": 1, "misses": 0}}
    new, _ = diff_live(state, {}, set(), RESUME_WINDOW * 10)
    assert new == {}


# ---- embeds ------------------------------------------------------------------------------------------------

def test_live_and_ended_embeds():
    s = twitch_stream()
    e = live_embed(s, "Ace", "http://avatar")
    assert e.url == s.url and e.title == "Pro Clubs night" and e.image.url == "http://img"
    assert any(f.name == "Playing" and f.value == "EA SPORTS FC 27" for f in e.fields)
    assert "LIVE" in e.author.name
    done = ended_embed(e)
    assert "ended" in done.description and "ended" in done.author.name
    assert done.image.url is None
    assert e.image.url == "http://img"          # the original is untouched


def test_embed_survives_missing_game_and_thumbnail():
    s = LiveStream(YOUTUBE, UC, "v1", "x" * 400, "", "https://www.youtube.com/watch?v=v1", "", "Ace")
    e = live_embed(s, "Ace")
    assert len(e.title) <= 256 and not any(f.name == "Playing" for f in e.fields)


# ---- API payloads ------------------------------------------------------------------------------------------

def test_parse_twitch_stream():
    item = {"id": "9", "user_login": "Ace", "user_name": "Ace", "game_name": "", "title": "t", "type": "live",
            "thumbnail_url": "https://x/{width}x{height}.jpg"}
    s = parse_twitch_stream(item, fallback_game="FC 27")
    assert s.channel_id == "ace" and s.game == "FC 27" and "1280x720" in s.thumbnail
    assert parse_twitch_stream({**item, "type": "rerun"}) is None


def test_parse_youtube_video():
    item = {"id": "v1", "snippet": {"channelId": UC, "title": "t", "channelTitle": "Ace", "liveBroadcastContent": "live",
                                      "thumbnails": {"high": {"url": "http://h"}}}, "liveStreamingDetails": {"actualStartTime": "x"}}
    s = parse_youtube_video(item)
    assert s.url.endswith("v1") and s.thumbnail == "http://h" and s.channel_id == UC
    assert parse_youtube_video({**item, "snippet": {**item["snippet"], "liveBroadcastContent": "none"}}) is None
    assert parse_youtube_video({**item, "liveStreamingDetails": {"actualEndTime": "y"}}) is None


# ---- the clients, against a fake session -------------------------------------------------------------------

class FakeResp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Answers by URL suffix from a list of (suffix, status, body); records every call."""

    def __init__(self, routes):
        self.routes, self.calls = list(routes), []

    def _answer(self, url, params, headers):
        self.calls.append((url, params, headers))
        for i, (suffix, status, body) in enumerate(self.routes):
            if url.endswith(suffix):
                if status == 401 and body is None:
                    self.routes.pop(i)      # a one-off 401, then the next matching route answers
                return FakeResp(status, body)
        raise AssertionError(f"unexpected call {url}")

    def get(self, url, params=None, headers=None):
        return self._answer(url, params, headers)

    def post(self, url, data=None):
        return self._answer(url, data, None)


def run(coro):
    return asyncio.run(coro)


def test_twitch_client_batches_and_refreshes_a_rejected_token():
    session = FakeSession([
        ("oauth2/token", 200, {"access_token": "tok", "expires_in": 3600}),
        ("helix/streams", 401, None),
        ("helix/streams", 200, {"data": [{"id": "1", "user_login": "ace", "user_name": "Ace", "title": "t",
                                           "type": "live", "game_name": "FC", "thumbnail_url": ""}]}),
    ])
    client = TwitchClient(session, "cid", "secret")
    streams = run(client.get_streams(["ace", "bob"]))
    assert [s.channel_id for s in streams] == ["ace"]
    tokens = [c for c in session.calls if c[0].endswith("oauth2/token")]
    assert len(tokens) == 2                                           # one refresh after the 401
    stream_calls = [c for c in session.calls if c[0].endswith("helix/streams")]
    assert stream_calls[-1][2]["Client-Id"] == "cid" and stream_calls[-1][2]["Authorization"] == "Bearer tok"


def test_twitch_client_splits_into_batches_of_100():
    session = FakeSession([("oauth2/token", 200, {"access_token": "t", "expires_in": 3600}),
                           ("helix/streams", 200, {"data": []}), ("helix/streams", 200, {"data": []})])
    run(TwitchClient(session, "c", "s").get_streams([f"user{i:03d}" for i in range(150)]))
    stream_calls = [c for c in session.calls if c[0].endswith("helix/streams")]
    assert len(stream_calls) == 2
    assert sum(1 for k, _ in stream_calls[0][1] if k == "user_login") == 100


def test_twitch_client_errors():
    bad = FakeSession([("oauth2/token", 400, {})])
    with pytest.raises(StreamAPIError):
        run(TwitchClient(bad, "c", "s").get_users(["ace"]))
    down = FakeSession([("oauth2/token", 200, {"access_token": "t", "expires_in": 3600}), ("helix/users", 500, {})])
    with pytest.raises(StreamAPIError) as info:
        run(TwitchClient(down, "c", "s").get_users(["ace"]))
    assert info.value.status == 500


def test_youtube_resolve_and_live_check():
    other = "UC" + "b" * 22
    session = FakeSession([
        ("youtube/v3/channels", 200, {"items": [{"id": UC, "snippet": {"title": "Ace"}}]}),
        (f"playlistItems", 200, {"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]}),
        ("youtube/v3/videos", 200, {"items": [
            {"id": "v1", "snippet": {"channelId": UC, "title": "old", "liveBroadcastContent": "none"}},
            {"id": "v2", "snippet": {"channelId": UC, "title": "live!", "channelTitle": "Ace", "liveBroadcastContent": "live"},
             "liveStreamingDetails": {}},
        ]}),
    ])
    client = YouTubeClient(session, "KEY")
    assert run(client.resolve(("handle", "@ace"))) == {"channel_id": UC, "name": "Ace"}
    assert session.calls[0][1]["forHandle"] == "@ace" and session.calls[0][1]["key"] == "KEY"
    live = run(client.live_now([UC]))
    assert [s.stream_id for s in live] == ["v2"]
    assert any(c[1].get("playlistId") == "UU" + "a" * 22 for c in session.calls)   # uploads playlist is UU + id[2:]
    assert run(YouTubeClient(FakeSession([("youtube/v3/channels", 200, {"items": []})]), "K").resolve(("id", other))) is None


def test_youtube_skips_a_missing_playlist_but_fails_on_quota():
    other = "UC" + "b" * 22
    session = FakeSession([("playlistItems", 404, {}), ("playlistItems", 200, {"items": []})])
    assert run(YouTubeClient(session, "K").live_now([UC, other])) == []
    quota = FakeSession([("playlistItems", 403, {})])
    with pytest.raises(StreamAPIError):
        run(YouTubeClient(quota, "K").live_now([UC]))


# ---- wiring ------------------------------------------------------------------------------------------------

def test_stream_pings_role_and_picker_button_exist():
    spec = next(r for r in ROLE_SPECS if r.name == ROLE_STREAMS)
    assert spec.mentionable and spec.managed
    assert any(role == ROLE_STREAMS for role, *_ in PICKER_ROLES)
    assert len({role for role, *_ in PICKER_ROLES}) == len(PICKER_ROLES) <= 5


# ---- the cog's polling loop, with fake Discord objects -----------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from qm.cogs.streams import Streams  # noqa: E402


class FakeMessage:
    def __init__(self, mid, content, embed):
        self.id, self.content, self.embeds = mid, content, [embed]

    async def edit(self, content=None, embed=None):
        self.content = content
        if embed is not None:
            self.embeds = [embed]


class FakeChannel:
    id = 900
    mention = "<#900>"

    def __init__(self):
        self.messages = {}
        self.sent = []

    async def send(self, content=None, embed=None, allowed_mentions=None):
        msg = FakeMessage(len(self.messages) + 1, content, embed)
        self.messages[msg.id] = msg
        self.sent.append((content, allowed_mentions))
        return msg

    async def fetch_message(self, mid):
        return self.messages[mid]


class FakeTwitch:
    def __init__(self):
        self.live = []

    async def get_streams(self, logins, games=None):
        return [s for s in self.live if s.channel_id in logins]


def make_cog():
    settings = Settings(os.path.join(tempfile.mkdtemp(), "cog.db"))
    channel = FakeChannel()
    ping = SimpleNamespace(id=7, name=ROLE_STREAMS, mentionable=True, mention="<@&7>")
    member = SimpleNamespace(id=42, display_name="Ace", display_avatar=SimpleNamespace(url="http://a"))
    guild = SimpleNamespace(
        id=1, roles=[ping], get_role=lambda rid: ping if rid == 7 else None,
        get_channel=lambda cid: channel if cid == 900 else None,
        get_member=lambda uid: member if uid == 42 else None,
    )
    settings.set(1, "channel:streams_clips", 900)
    settings.set(1, "role:stream_pings", 7)
    save_links(settings, 1, [{"user_id": 42, "platform": TWITCH, "channel_id": "ace", "name": "Ace", "game": ""}])
    bot = SimpleNamespace(settings=settings, guilds=[guild])
    cog = Streams(bot)
    cog.twitch = FakeTwitch()
    return cog, guild, channel


def test_cog_announces_once_then_marks_the_post_ended():
    cog, guild, channel = make_cog()
    cog.twitch.live = [twitch_stream()]

    run(cog._poll_guild(guild, youtube_due=False))
    run(cog._poll_guild(guild, youtube_due=False))
    assert len(channel.sent) == 1                                   # posted once, not on every poll
    content, mentions = channel.sent[0]
    assert content.startswith("<@&7>") and "Ace" in content
    assert mentions.roles and not mentions.everyone and not mentions.users
    post = channel.messages[1]
    assert "LIVE" in post.embeds[0].author.name

    cog.twitch.live = []
    for _ in range(END_AFTER_MISSES):
        run(cog._poll_guild(guild, youtube_due=False))
    assert "ended" in post.embeds[0].description and post.content is None

    cog.twitch.live = [twitch_stream("s2")]                          # back within the window: same post, no new ping
    run(cog._poll_guild(guild, youtube_due=False))
    assert len(channel.sent) == 1 and "ended" not in post.embeds[0].description


def test_cog_skips_members_who_left_and_survives_a_platform_outage():
    cog, guild, channel = make_cog()
    save_links(cog.bot.settings, 1, [{"user_id": 99, "platform": TWITCH, "channel_id": "ace", "name": "Ace", "game": ""}])
    cog.twitch.live = [twitch_stream()]
    run(cog._poll_guild(guild, youtube_due=False))
    assert channel.sent == []                                        # user 99 isn't in the server

    cog2, guild2, channel2 = make_cog()
    cog2.twitch.live = [twitch_stream()]
    run(cog2._poll_guild(guild2, youtube_due=False))

    async def boom(*a, **k):
        raise StreamAPIError("down", 500)
    cog2.twitch.get_streams = boom
    for _ in range(5):
        run(cog2._poll_guild(guild2, youtube_due=False))
    assert "LIVE" in channel2.messages[1].embeds[0].author.name       # an outage doesn't end the stream
