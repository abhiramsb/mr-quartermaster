"""Stream alerts: link parsing, Twitch and YouTube clients, and the pure "who just went live" logic.

Everything here is testable without Discord or the network, except the two small API clients, which take
an aiohttp-style session so tests can hand them a fake one.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import aiohttp
import discord

TWITCH = "twitch"
YOUTUBE = "youtube"
PLATFORM_LABEL = {TWITCH: "Twitch", YOUTUBE: "YouTube"}
PLATFORM_COLOR = {TWITCH: 0x9146FF, YOUTUBE: 0xFF0000}

END_AFTER_MISSES = 2          # polls in a row that must say "offline" before we call a stream ended
RESUME_WINDOW = 20 * 60       # seconds; a stream that comes back within this window reuses its old post
ENDED_COLOR = 0x7F8C8D
UPLOAD_MAX_AGE = 48 * 3600    # seconds; an upload older than this is recorded as seen but never announced
UPLOAD_MAX_PER_POLL = 3       # per channel; a burst of uploads can't flood the channel
UPLOAD_SEEN_KEEP = 50         # video IDs remembered per channel
SHORTS_MAX_SECONDS = 180      # YouTube Shorts can be up to 3 minutes; anything longer is never a Short
SHORTS_SURE_SECONDS = 60      # fallback guess when the Shorts check can't be made: this short is treated as a Short
UPLOAD_COLOR = 0xCC0000
PRESENCE_ID = "presence"      # stream_id used when we only know about a stream from Discord's "Streaming" status


class StreamAPIError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LiveStream:
    platform: str
    channel_id: str       # twitch login (lowercase) or YouTube channel ID
    stream_id: str
    title: str
    game: str
    url: str
    thumbnail: str
    name: str             # the streamer's channel name as the platform shows it

    @property
    def key(self) -> str:
        return link_key(self.platform, self.channel_id)


@dataclass(frozen=True)
class Upload:
    """A normal (non-live) YouTube video that has just appeared on a linked channel."""
    channel_id: str       # YouTube channel ID (UC...)
    video_id: str
    title: str
    url: str
    thumbnail: str
    name: str             # the channel name as YouTube shows it
    published_at: float   # unix seconds; 0 if unknown
    duration: Optional[int]   # seconds; None if unknown


def link_key(platform: str, channel_id: str) -> str:
    return f"{platform}:{channel_id}"


def alert_kinds(platform: str) -> str:
    """What a linked channel on this platform gets announced for, in words for the /stream link reply."""
    if platform == YOUTUBE:
        return "go live or upload a new video (Shorts are skipped)"
    return "go live"


_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso_duration(text: str) -> Optional[int]:
    """Seconds from a YouTube ISO 8601 duration such as PT1M5S; None if it can't be read."""
    m = _ISO_DURATION.match(text or "")
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_iso_time(text: str) -> float:
    """Unix seconds from a YouTube timestamp such as 2026-11-23T10:00:00Z; 0 if it can't be read."""
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# ---- reading what a member typed ---------------------------------------------------------------------------

_TWITCH_URL = re.compile(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)/?(?:[?#].*)?$", re.I)
_TWITCH_LOGIN = re.compile(r"^[a-z0-9_]{3,25}$")
_YT_ID = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
_YT_URL = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.\-]{3,30}|channel/UC[0-9A-Za-z_-]{22})/?(?:[/?#].*)?$", re.I
)
_YT_HANDLE = re.compile(r"^@?[\w.\-]{3,30}$")


def parse_twitch(text: str) -> Optional[str]:
    """A Twitch login from a name, @name or twitch.tv link; None if it can't be one."""
    t = text.strip()
    m = _TWITCH_URL.match(t)
    if m:
        t = m.group(1)
    t = t.lstrip("@").lower()
    return t if _TWITCH_LOGIN.match(t) else None


_YT_VIDEO = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})", re.I)


def youtube_video_id(url: str) -> Optional[str]:
    m = _YT_VIDEO.search(url or "")
    return m.group(1) if m else None


def parse_youtube(text: str) -> Optional[tuple[str, str]]:
    """("id", "UC...") or ("handle", "@name") from a handle, channel ID or youtube.com link; else None.

    Old-style /c/ and /user/ links aren't supported, because the API can't resolve them reliably.
    """
    t = text.strip()
    m = _YT_URL.match(t)
    if m:
        t = m.group(1)
        if t.lower().startswith("channel/"):
            t = t[len("channel/"):]
    if _YT_ID.match(t):
        return ("id", t)
    if _YT_HANDLE.match(t):
        return ("handle", t if t.startswith("@") else "@" + t)
    return None


# ---- the stored links and state ----------------------------------------------------------------------------

def load_links(settings, guild_id: int) -> list[dict]:
    try:
        data = json.loads(settings.get(guild_id, "streams:links", "[]") or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def save_links(settings, guild_id: int, links: list[dict]) -> None:
    settings.set(guild_id, "streams:links", json.dumps(links))


def load_state(settings, guild_id: int) -> dict:
    try:
        data = json.loads(settings.get(guild_id, "streams:state", "{}") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(settings, guild_id: int, state: dict) -> None:
    settings.set(guild_id, "streams:state", json.dumps(state))


def load_upload_state(settings, guild_id: int) -> dict:
    """channel_id -> {"seen": [video IDs]} for YouTube upload alerts."""
    try:
        data = json.loads(settings.get(guild_id, "streams:uploads", "{}") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_upload_state(settings, guild_id: int, state: dict) -> None:
    settings.set(guild_id, "streams:uploads", json.dumps(state))


def add_link(links: list[dict], user_id: int, platform: str, channel_id: str, name: str, game: str) -> tuple[list[dict], Optional[int]]:
    """Add or replace the member's link for this platform.

    Returns (new links, other_user_id). other_user_id is set, and nothing is added, when someone else
    already linked that same channel.
    """
    for link in links:
        if link["platform"] == platform and link["channel_id"] == channel_id and link["user_id"] != user_id:
            return links, link["user_id"]
    kept = [l for l in links if not (l["user_id"] == user_id and l["platform"] == platform)]
    kept.append({"user_id": user_id, "platform": platform, "channel_id": channel_id, "name": name, "game": game})
    return kept, None


def remove_link(links: list[dict], user_id: int, platform: str) -> tuple[list[dict], bool]:
    kept = [l for l in links if not (l["user_id"] == user_id and l["platform"] == platform)]
    return kept, len(kept) != len(links)


# ---- Discord's own "Streaming" status ----------------------------------------------------------------------

def presence_stream(
    url: str, title: str, game: str, display_name: str, user_id: int, links: list[dict]
) -> Optional[LiveStream]:
    """Turn a member's Discord "Streaming" activity into a LiveStream, or None for other platforms.

    A Twitch stream is keyed by its login, so it matches the same member's /stream link and is never posted
    twice. A YouTube stream is keyed by the member's linked channel if they have one (its video ID then also
    matches what the API reports); otherwise by their Discord ID.
    """
    url = (url or "").strip()
    mine = {l["platform"]: l for l in links if l["user_id"] == user_id}
    if "twitch.tv" in url.lower():
        login = parse_twitch(url)
        if not login:
            return None
        linked = mine.get(TWITCH)
        thumb = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-1280x720.jpg?t={int(time.time() // 60)}"
        return LiveStream(
            platform=TWITCH, channel_id=login, stream_id=PRESENCE_ID, title=title or "", url=f"https://www.twitch.tv/{login}",
            game=game or (linked or {}).get("game", ""), thumbnail=thumb, name=login,
        )
    video = youtube_video_id(url)
    if not video:
        return None
    linked = mine.get(YOUTUBE)
    return LiveStream(
        platform=YOUTUBE, channel_id=linked["channel_id"] if linked else f"presence-{user_id}", stream_id=video,
        title=title or "", game=game or (linked or {}).get("game", ""), url=f"https://www.youtube.com/watch?v={video}",
        thumbnail="", name=(linked or {}).get("name") or display_name,
    )


# ---- who just went live ------------------------------------------------------------------------------------

def diff_live(
    state: dict, live_now: dict[str, LiveStream], polled: set[str], now: float
) -> tuple[dict, list[tuple[str, str]]]:
    """Work out what to do after a poll.

    state:    key -> {"live", "stream_id", "message_id", "ended_at", "misses"} from earlier polls
    live_now: key -> LiveStream for everything the poll saw live
    polled:   keys whose platform answered this time. A key that wasn't polled (API down) is left alone, so
              an outage never ends a stream or re-announces one.
    Returns (new_state, actions). Actions are ("announce"|"resume"|"end", key). The caller posts the message
    and then stores message_id on new_state[key].
    """
    new = {k: dict(v) for k, v in state.items()}
    actions: list[tuple[str, str]] = []

    for key, stream in live_now.items():
        entry = new.get(key)
        if entry is not None and entry.get("live"):
            entry["misses"] = 0
            old_id, new_id = entry.get("stream_id"), stream.stream_id
            if old_id != new_id and PRESENCE_ID not in (old_id, new_id):
                new[key] = {"live": True, "stream_id": new_id, "message_id": None, "ended_at": None, "misses": 0}
                actions.append(("announce", key))
            elif old_id == PRESENCE_ID and new_id != PRESENCE_ID:
                entry["stream_id"] = new_id   # the API has caught up with what Discord showed; keep the same post
            continue
        ended_at = entry.get("ended_at") if entry else None
        if entry is not None and ended_at is not None and now - ended_at <= RESUME_WINDOW and entry.get("message_id"):
            entry.update({"live": True, "stream_id": stream.stream_id, "ended_at": None, "misses": 0})
            actions.append(("resume", key))
        else:
            new[key] = {"live": True, "stream_id": stream.stream_id, "message_id": None, "ended_at": None, "misses": 0}
            actions.append(("announce", key))

    for key, entry in new.items():
        if key in live_now or not entry.get("live") or key not in polled:
            continue
        entry["misses"] = entry.get("misses", 0) + 1
        if entry["misses"] >= END_AFTER_MISSES:
            entry.update({"live": False, "ended_at": now, "misses": 0})
            actions.append(("end", key))

    # forget old finished entries so the stored state doesn't grow forever
    stale = [
        k for k, v in new.items()
        if not v.get("live") and v.get("ended_at") is not None and now - v["ended_at"] > RESUME_WINDOW * 6
    ]
    for key in stale:
        del new[key]
    return new, actions


# ---- new uploads -------------------------------------------------------------------------------------------

def diff_uploads(
    state: dict, uploads: list[Upload], polled: set[str], linked: set[str], now: float
) -> tuple[dict, list[Upload]]:
    """Work out which uploads are new after a YouTube check.

    state:   channel_id -> {"seen": [video IDs]} from earlier checks
    uploads: every recent normal video the check saw
    polled:  channel IDs the check actually covered. A channel that wasn't covered is left alone.
    linked:  channel IDs that are linked now. State for anything else is dropped.
    Returns (new_state, to_announce), oldest first.

    A channel seen for the first time is only recorded, never announced, so linking a channel (or deploying this)
    doesn't post its old videos. Anything older than UPLOAD_MAX_AGE is recorded but not announced, and at most
    UPLOAD_MAX_PER_POLL per channel go out at once (the newest ones).
    """
    new = {cid: {"seen": list(entry.get("seen", []))} for cid, entry in state.items() if cid in linked}
    by_channel: dict[str, list[Upload]] = {}
    for up in uploads:
        by_channel.setdefault(up.channel_id, []).append(up)
    announce: list[Upload] = []
    for cid in polled & linked:
        videos = sorted(by_channel.get(cid, []), key=lambda u: u.published_at)
        entry = new.get(cid)
        if entry is None:                        # first sight: remember what's there, say nothing
            new[cid] = {"seen": [u.video_id for u in videos][-UPLOAD_SEEN_KEEP:]}
            continue
        seen = entry["seen"]
        fresh = [
            u for u in videos
            if u.video_id not in seen and u.published_at and now - u.published_at <= UPLOAD_MAX_AGE
        ]
        seen.extend(u.video_id for u in videos if u.video_id not in seen)
        entry["seen"] = seen[-UPLOAD_SEEN_KEEP:]
        announce.extend(fresh[-UPLOAD_MAX_PER_POLL:])
    return new, announce


# ---- embeds ------------------------------------------------------------------------------------------------

def upload_embed(upload: Upload, display_name: str, avatar_url: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=(upload.title or "New video")[:256],
        url=upload.url,
        description=f"**{display_name}** uploaded a new video on YouTube.",
        colour=discord.Colour(UPLOAD_COLOR),
    )
    embed.add_field(name="Watch", value=f"[{upload.name or 'YouTube'}]({upload.url})", inline=True)
    if upload.thumbnail:
        embed.set_image(url=upload.thumbnail)
    embed.set_author(name=f"{display_name} · NEW VIDEO", icon_url=avatar_url)
    embed.set_footer(text="YouTube")
    return embed


def live_embed(stream: LiveStream, display_name: str, avatar_url: Optional[str] = None) -> discord.Embed:
    label = PLATFORM_LABEL[stream.platform]
    embed = discord.Embed(
        title=(stream.title or "Live now")[:256],
        url=stream.url,
        description=f"**{display_name}** is live on {label}. Come hang out!",
        colour=discord.Colour(PLATFORM_COLOR[stream.platform]),
    )
    if stream.game:
        embed.add_field(name="Playing", value=stream.game[:1000], inline=True)
    embed.add_field(name="Watch", value=f"[{stream.name}]({stream.url})", inline=True)
    if stream.thumbnail:
        embed.set_image(url=stream.thumbnail)
    embed.set_author(name=f"{display_name} · LIVE", icon_url=avatar_url)
    embed.set_footer(text=label)
    return embed


def ended_embed(old: discord.Embed) -> discord.Embed:
    """The same post, greyed out, once the stream is over."""
    embed = old.copy()
    embed.colour = discord.Colour(ENDED_COLOR)
    embed.description = "This stream has ended. Catch the next one!"
    embed.set_image(url=None)
    if embed.author and embed.author.name:
        embed.set_author(name=embed.author.name.replace("· LIVE", "· ended"), icon_url=embed.author.icon_url)
    return embed


# ---- API clients -------------------------------------------------------------------------------------------

def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def parse_twitch_stream(item: dict, fallback_game: str = "") -> Optional[LiveStream]:
    if item.get("type") not in (None, "live"):
        return None
    login = str(item.get("user_login", "")).lower()
    if not login or not item.get("id"):
        return None
    thumb = str(item.get("thumbnail_url", "")).replace("{width}", "1280").replace("{height}", "720")
    if thumb:
        thumb += f"?t={int(time.time() // 60)}"  # Twitch caches thumbnails; a new value per minute refreshes it
    return LiveStream(
        platform=TWITCH, channel_id=login, stream_id=str(item["id"]), title=item.get("title", ""),
        game=item.get("game_name") or fallback_game, url=f"https://www.twitch.tv/{login}",
        thumbnail=thumb, name=item.get("user_name") or login,
    )


def parse_youtube_video(item: dict) -> Optional[LiveStream]:
    snippet = item.get("snippet", {})
    details = item.get("liveStreamingDetails", {})
    if snippet.get("liveBroadcastContent") != "live" or details.get("actualEndTime"):
        return None
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}).get("url", "")
    return LiveStream(
        platform=YOUTUBE, channel_id=snippet.get("channelId", ""), stream_id=str(item.get("id", "")),
        title=snippet.get("title", ""), game="", url=f"https://www.youtube.com/watch?v={item.get('id', '')}",
        thumbnail=thumb, name=snippet.get("channelTitle", ""),
    )


def parse_youtube_upload(item: dict) -> Optional[Upload]:
    """A finished, ordinary video; None for live, upcoming and past-livestream videos (those are stream alerts)."""
    snippet = item.get("snippet", {})
    if snippet.get("liveBroadcastContent") not in (None, "none") or item.get("liveStreamingDetails"):
        return None
    video_id = str(item.get("id", ""))
    if not video_id or not snippet.get("channelId"):
        return None
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("medium") or {}).get("url", "")
    return Upload(
        channel_id=snippet["channelId"], video_id=video_id, title=snippet.get("title", ""),
        url=f"https://www.youtube.com/watch?v={video_id}", thumbnail=thumb, name=snippet.get("channelTitle", ""),
        published_at=parse_iso_time(snippet.get("publishedAt", "")),
        duration=parse_iso_duration(item.get("contentDetails", {}).get("duration", "")),
    )


class TwitchClient:
    """Twitch Helix with an app token (client credentials). Needs a free app at dev.twitch.tv."""

    def __init__(self, session, client_id: str, client_secret: str):
        self.session = session
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._expires = 0.0

    async def _ensure_token(self, force: bool = False) -> str:
        if self._token and not force and time.time() < self._expires - 60:
            return self._token
        async with self.session.post(
            "https://id.twitch.tv/oauth2/token",
            data={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials"},
        ) as resp:
            if resp.status != 200:
                raise StreamAPIError(f"Twitch refused the app credentials ({resp.status})", resp.status)
            body = await resp.json()
        self._token = body["access_token"]
        self._expires = time.time() + float(body.get("expires_in", 3600))
        return self._token

    async def _get(self, path: str, params: list[tuple[str, str]]) -> dict:
        for attempt in (0, 1):
            token = await self._ensure_token(force=attempt == 1)
            headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {token}"}
            async with self.session.get(f"https://api.twitch.tv/helix/{path}", params=params, headers=headers) as resp:
                if resp.status == 401 and attempt == 0:
                    continue  # token expired early; fetch a new one and retry once
                if resp.status != 200:
                    raise StreamAPIError(f"Twitch answered {resp.status}", resp.status)
                return await resp.json()
        raise StreamAPIError("Twitch kept refusing the token", 401)

    async def get_users(self, logins: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for batch in _chunks(logins, 100):
            body = await self._get("users", [("login", l) for l in batch])
            for u in body.get("data", []):
                found[u["login"].lower()] = u
        return found

    async def get_streams(self, logins: list[str], games: Optional[dict[str, str]] = None) -> list[LiveStream]:
        games = games or {}
        out: list[LiveStream] = []
        for batch in _chunks(logins, 100):
            body = await self._get("streams", [("user_login", l) for l in batch] + [("first", "100")])
            for item in body.get("data", []):
                stream = parse_twitch_stream(item, games.get(str(item.get("user_login", "")).lower(), ""))
                if stream:
                    out.append(stream)
        return out


class YouTubeClient:
    """YouTube Data API v3 with an API key. Checks each channel's newest uploads, which costs about 2 quota
    units per channel per check (the live-search call would cost 100)."""

    def __init__(self, session, api_key: str):
        self.session = session
        self.api_key = api_key

    async def _get(self, path: str, params: dict) -> dict:
        async with self.session.get(
            f"https://www.googleapis.com/youtube/v3/{path}", params={**params, "key": self.api_key}
        ) as resp:
            if resp.status != 200:
                raise StreamAPIError(f"YouTube answered {resp.status}", resp.status)
            return await resp.json()

    async def resolve(self, ref: tuple[str, str]) -> Optional[dict]:
        """{"channel_id", "name"} for ("id", ...) or ("handle", ...); None if it doesn't exist."""
        kind, value = ref
        params = {"part": "snippet", ("id" if kind == "id" else "forHandle"): value}
        body = await self._get("channels", params)
        items = body.get("items") or []
        if not items:
            return None
        return {"channel_id": items[0]["id"], "name": items[0].get("snippet", {}).get("title", value)}

    async def live_now(self, channel_ids: list[str]) -> list[LiveStream]:
        return (await self.scan(channel_ids))[0]

    async def is_short(self, upload: Upload) -> bool:
        """True if the video is a YouTube Short. The API has no flag for it, so: anything over 3 minutes isn't one;
        otherwise ask YouTube's /shorts/ page, which stays put for a Short and redirects for an ordinary video.
        If that can't be checked, a video of a minute or less is treated as a Short."""
        if upload.duration is None or upload.duration > SHORTS_MAX_SECONDS:
            return False
        try:
            async with self.session.head(f"https://www.youtube.com/shorts/{upload.video_id}", allow_redirects=False) as resp:
                if resp.status == 200:
                    return True
                if 300 <= resp.status < 400:
                    return False
        except (aiohttp.ClientError, OSError):
            pass
        return upload.duration <= SHORTS_SURE_SECONDS

    async def scan(self, channel_ids: list[str]) -> tuple[list[LiveStream], list[Upload]]:
        """One pass over each channel's newest videos: (streams live now, ordinary recent uploads).
        Both come from the same two API calls, so upload alerts cost no extra quota."""
        video_ids: list[str] = []
        for cid in channel_ids:
            if not _YT_ID.match(cid):
                continue
            try:
                body = await self._get(
                    "playlistItems", {"part": "contentDetails", "playlistId": "UU" + cid[2:], "maxResults": 5}
                )
            except StreamAPIError as exc:
                if exc.status == 404:   # deleted channel or hidden uploads; skip it instead of failing everyone
                    continue
                raise
            video_ids += [i["contentDetails"]["videoId"] for i in body.get("items", []) if "contentDetails" in i]
        wanted = set(channel_ids)
        seen: set[str] = set()
        live: list[LiveStream] = []
        uploads: list[Upload] = []
        for batch in _chunks(video_ids, 50):
            body = await self._get(
                "videos", {"part": "snippet,liveStreamingDetails,contentDetails", "id": ",".join(batch)}
            )
            for item in body.get("items", []):
                stream = parse_youtube_video(item)
                if stream and stream.channel_id in wanted and stream.channel_id not in seen:
                    seen.add(stream.channel_id)
                    live.append(stream)
                    continue
                upload = parse_youtube_upload(item)
                if upload and upload.channel_id in wanted:
                    uploads.append(upload)
        return live, uploads
