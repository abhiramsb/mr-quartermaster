# MR_Quartermaster

The server-level bot for **Millennial Regiment Gaming**. It builds the server layout, welcomes and sends off
members, hands out roles, and lets MRFC Captains manage the squad. The football-specific bots
(MRFC_GroundsKeeper, MRFC_Scout, MRFC_Coach) live in their own repos.

## What it does
- **#reception:** a random welcome when someone joins, a random send-off when they leave, and the **Recruit** role on join.
  When a member welcomes a newcomer there (replies to the welcome post, or mentions someone who joined in the last 2 days),
  the bot answers with a line and a GIF (once per member every 5 minutes). Customise it with `/reception line|gif` kind **greet**.
  The server-wide lines contain no football words. Each message can include a random GIF from a list you curate.
- **Game welcome and send-off:** when someone picks **Football Club**, a colourful football welcome posts in `#reception`;
  when they deselect it, a football send-off posts there. Repeated toggling within 5 minutes is ignored.
  All welcomes and send-offs go to `#reception`; nothing is posted in the chat channels.
  Other games can get their own later (see `qm/messages.py`).
- **Role-picker** in `#pick-your-roles`: persistent buttons for **Football Club** (unlocks the MRFC section),
  **Event Pings**, **News Pings** and **Stream Pings**.
- **`/setup run`:** creates or updates the roles, categories, channels and permissions below. Previews by default.
- **`/setup migrate`:** moves existing members to the new roles. Previews by default. Everyone gets **Recruit** and
  **Football Club**; the server owner (or the member you pick with `captain`) also becomes **MRFC Captain** and
  **MRFC Squad**. Nobody else gets Captain or Squad. Options: `give_football_club_to_all`, `remove_old_role`, and
  `announce`, which posts a relaunch announcement with a roll call in `#announcements` and one combined football welcome in `#reception`
  (off by default, so you can migrate quietly first).
- **`/setup status`:** shows what is configured and what needs fixing.
- **`/squad add | remove | list`:** MRFC Captains manage the Squad role without needing Manage Roles.
- **`/announce`:** staff post an announcement embed, optionally pinging a role.
- **`/reception line add | list | remove`:** add your own lines to the welcome, send-off or football pools.
- **`/reception gif add | list | remove`:** curate the GIFs (https links; direct `.gif` links show inside the message,
  Tenor or Giphy page links show as an animation under it). The lists start with a curated set from `qm/seed_gifs.json` (animals and lettering,
  loaded once per server, never overwriting your changes).
- **`/reception preview`:** a random sample of each message (only you see it).
- **`/rolepicker`:** repost the picker in the current channel.
- **Go-live alerts:** members link a channel with `/stream link`, and when they go live on Twitch or YouTube the bot
  posts an embed (title, game, thumbnail, watch link) in `#streams-n-clips`, pinging **Stream Pings**. Members who show a
  Twitch or YouTube "Streaming" status on Discord are announced instantly even without linking. The post is greyed
  out when the stream ends, and a stream that drops and returns within 20 minutes reuses its post instead of pinging again.
  See *Stream alerts* below.
- **`#bot-logs`:** joins, leaves, role changes and bans.

## Roles (top to bottom)
Admin, Mod, *(this bot's role)*, **MRFC Captain**, **MRFC Squad**, **Football Club**, **Recruit**, Event Pings, News Pings, Stream Pings.

Admin and Mod are created if missing, with **no special permissions**. Give them their permissions yourself and keep
them above this bot's role. The bot places the roles below its own and cannot grant anything it doesn't hold.

## Channels
| Category | Channels | Who |
|---|---|---|
| HQ | `#reception`, `#rules`, `#announcements`, `#pick-your-roles` | everyone reads; staff post in announcements |
| MRFC *(hidden until Football Club)* | `#mrfc-announcements`, `#mrfc-chat`, `#mrfc-sessions`, voice: MRFC Lobby | Football Club and up (Captains post in announcements and sessions) |
| | `#mrfc-tactics` | Squad and Captains |
| | `#mrfc-scouting`, `#mrfc-captains`, voice: Captains' Room | Captains only |
| THE BARRACKS | `#general`, `#streams-n-clips`, `#looking-for-group`, `#off-topic`, voice: General Lounge, Lounge 2 | Recruit and up |
| STAFF | `#staff-chat`, `#bot-logs`, `#bot-commands` | Admin and Mod |

Squad members also hold Football Club (`/squad add` grants both), so they keep access to the shared MRFC channels.


### Moving an existing server onto this layout

`/setup run` renames and moves channels it recognises instead of creating duplicates, so run the dry run first and
read the preview. Channels outside the layout are never deleted.

| Existing channel | Becomes |
|---|---|
| `#get-roles` | `#pick-your-roles` (HQ) |
| `#rules` | `#rules` (HQ) |
| `#the-reception` | `#reception` (HQ) |
| `#general` | `#general` (THE BARRACKS) |
| `#streams-n-clips` | `#streams-n-clips` (THE BARRACKS) |
| `#sessions` | `#mrfc-sessions` |
| `#tactics` | `#mrfc-tactics` |
| `#scouting` | `#mrfc-scouting` |
| `#captains-corner` | `#mrfc-captains` |
| `#locker-room` | `#mrfc-locker-room` (Squad and Captains only) |
| voice `Lobby` | `MRFC Lobby` |
| voice `Timepass` | `General Lounge` |

Anything not listed stays where it is. The old empty categories can be deleted by hand.

## Stream alerts
Two sources feed the same alerts, and a stream both of them see is posted once.

1. **Discord's Streaming status** (instant, no keys, no linking). A member who has connected Twitch or YouTube in
   *Settings → Connections* with "Display on profile" on shows as Streaming when they go live, and the bot posts it.
   Needs the **Presence Intent** (see Setup). Staff can switch it on or off with `/stream presence`. It only starts alerts;
   a status that flickers can never end one. Embed details are plainer (title and game from the status, a Twitch preview
   image, no thumbnail for YouTube). Reliable for Twitch; YouTube depends on Discord's connection.
2. **The platforms' APIs** (richer embed, works whatever the member's Discord settings). Members link a channel first.

Commands: `/stream link <platform> <channel> [game]`, `/stream unlink <platform>`, `/stream list`, `/stream presence`
and `/stream status` (staff). Staff can pass `member` to link or unlink someone else. Each member can have one Twitch and
one YouTube channel.

The API source is off for a platform until its keys are set (see the variables below). A platform with no keys just says
so when someone tries to link.
- **Twitch:** create a free app at https://dev.twitch.tv/console and copy the client ID and secret. Checked every minute.
  The game comes from Twitch.
- **YouTube:** in Google Cloud, enable *YouTube Data API v3* and create an API key. Checked every two minutes, by looking
  at each linked channel's newest uploads (about 2 quota units per channel per check, so roughly 10 linked channels fit in
  the free 10,000 units a day). Members can add a `game` when linking, since YouTube doesn't expose one reliably.
  Use an `@handle`, a `youtube.com/@handle` or `youtube.com/channel/UC...` link, or the channel ID.

Things to know:
- Linking is on trust: the bot checks that the channel exists but can't prove it belongs to the member. Staff can remove any link.
- A stream is ended only after two timer checks in a row say offline, and a platform outage never ends or re-posts a stream.
- Members who don't want to be announced can turn off "Display on profile" for their connection, or set their status to invisible.
- Alerts can arrive a minute or two after going live, and YouTube can lag a little more.

## Setup
1. **Developer Portal** (https://discord.com/developers/applications) -> your application -> **Bot**:
   copy the token, and turn on **Server Members Intent** and **Presence Intent** (both privileged). If the bot won't start and
   the log mentions privileged intents, one of these is off. You can run without presence by setting `PRESENCE_INTENT=0`.
2. **Invite** the bot with this permission integer, `271666192`:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=271666192`
   (View Channels, Send Messages, Embed Links, Read Message History, Manage Roles, Manage Channels, Connect, Speak.)
3. In the server, drag the bot's role **above** the roles it will hand out (Recruit, Football Club, Squad, Captain),
   and keep Admin and Mod above it.
4. Set the environment variables below on your host and start it with `python main.py`.
5. Run `/setup run` (preview), read the list, then run `/setup run dry_run:False`.
6. Run `/setup migrate` (preview), then again with `dry_run:False`. Add `announce:True` when you're ready to announce.
7. Write your rules in `#rules`.

If you already have channels, `/setup run` renames and moves the ones it recognises (see *Moving an existing server onto
this layout*) and leaves every other channel alone. Its preview lists each change before anything happens.

## Environment variables
| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | bot token (required) |
| `DEV_GUILD_ID` | optional: sync commands instantly to one server while testing |
| `DB_PATH` | settings database, default `quartermaster.db` (keep it on persistent storage) |
| `GROUNDSKEEPER_BOT_ID` | optional: the scheduler bot's user ID, so `/setup` gives it `#mrfc-sessions` |
| `COACH_BOT_ID` | optional: the coach bot's user ID, for `#mrfc-tactics` |
| `SCOUT_BOT_ID` | optional: the scout bot's user ID, for `#mrfc-scouting` |
| `PRESENCE_INTENT` | default on; set `0` to run without the Presence Intent (no alerts from Discord's Streaming status) |
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | optional: switch on Twitch go-live alerts |
| `YOUTUBE_API_KEY` | optional: switch on YouTube go-live alerts |

## Develop
```
pip install -r requirements.txt pytest
python -m pytest -q
```
The tests cover the layout and who can see or post where, using Discord's permission rules. They do not talk to Discord.
