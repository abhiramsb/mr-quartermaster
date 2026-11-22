# MR_Quartermaster

The server-level bot for **Millennial Regiment Gaming**. It builds the server layout, welcomes and sends off
members, hands out roles, and lets MRFC Captains manage the squad. The football-specific bots
(MRFC_GroundsKeeper, MRFC_Scout, MRFC_Coach) live in their own repos.

## What it does
- **#reception:** a random welcome when someone joins, a random send-off when they leave, and the **Recruit** role on join.
  The server-wide lines contain no football words. Each message can include a random GIF from a list you curate.
- **Game welcome and send-off:** when someone picks **Football Club**, a colourful football welcome posts in `#reception`;
  when they deselect it, a football send-off posts there. Repeated toggling within 5 minutes is ignored.
  All welcomes and send-offs go to `#reception`; nothing is posted in the chat channels.
  Other games can get their own later (see `qm/messages.py`).
- **Role-picker** in `#pick-your-roles`: persistent buttons for **Football Club** (unlocks the MRFC section),
  **Event Pings** and **News Pings**.
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
- **`#bot-logs`:** joins, leaves, role changes and bans.

## Roles (top to bottom)
Admin, Mod, *(this bot's role)*, **MRFC Captain**, **MRFC Squad**, **Football Club**, **Recruit**, Event Pings, News Pings.

Admin and Mod are created if missing, with **no special permissions**. Give them their permissions yourself and keep
them above this bot's role. The bot places the roles below its own and cannot grant anything it doesn't hold.

## Channels
| Category | Channels | Who |
|---|---|---|
| HQ | `#reception`, `#rules`, `#announcements`, `#pick-your-roles` | everyone reads; staff post in announcements |
| MRFC *(hidden until Football Club)* | `#mrfc-announcements`, `#mrfc-chat`, `#mrfc-sessions`, voice: MRFC Lobby | Football Club and up (Captains post in announcements and sessions) |
| | `#mrfc-tactics` | Squad and Captains |
| | `#mrfc-scouting`, `#mrfc-captains`, voice: Captains' Room | Captains only |
| GENERAL | `#general`, `#streams-n-clips` *(renamed from `#media` if it exists)*, `#looking-for-group`, `#off-topic`, voice: General Lounge, Lounge 2 | Recruit and up |
| STAFF | `#staff-chat`, `#bot-logs`, `#bot-commands` | Admin and Mod |

Squad members also hold Football Club (`/squad add` grants both), so they keep access to the shared MRFC channels.

## Setup
1. **Developer Portal** (https://discord.com/developers/applications) -> your application -> **Bot**:
   copy the token, and turn on **Server Members Intent** (privileged).
2. **Invite** the bot with this permission integer, `271666192`:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=271666192`
   (View Channels, Send Messages, Embed Links, Read Message History, Manage Roles, Manage Channels, Connect, Speak.)
3. In the server, drag the bot's role **above** the roles it will hand out (Recruit, Football Club, Squad, Captain),
   and keep Admin and Mod above it.
4. Set the environment variables below on your host and start it with `python main.py`.
5. Run `/setup run` (preview), read the list, then run `/setup run dry_run:False`.
6. Run `/setup migrate` (preview), then again with `dry_run:False`. Add `announce:True` when you're ready to announce.
7. Write your rules in `#rules`.

If you already have channels named like these, `/setup run` reports when a category already exists and how many extra
channels it holds. Move old channels into an archive category first if you don't want them touched.

## Environment variables
| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | bot token (required) |
| `DEV_GUILD_ID` | optional: sync commands instantly to one server while testing |
| `DB_PATH` | settings database, default `quartermaster.db` (keep it on persistent storage) |
| `GROUNDSKEEPER_BOT_ID` | optional: the scheduler bot's user ID, so `/setup` gives it `#mrfc-sessions` |
| `COACH_BOT_ID` | optional: the coach bot's user ID, for `#mrfc-tactics` |
| `SCOUT_BOT_ID` | optional: the scout bot's user ID, for `#mrfc-scouting` |

## Develop
```
pip install -r requirements.txt pytest
python -m pytest -q
```
The tests cover the layout and who can see or post where, using Discord's permission rules. They do not talk to Discord.
