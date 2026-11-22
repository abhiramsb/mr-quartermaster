"""/stream: members link their Twitch or YouTube channel and the bot announces when they go live."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..layout import ROLE_STREAMS
from ..streams import (
    PLATFORM_LABEL,
    TWITCH,
    YOUTUBE,
    StreamAPIError,
    TwitchClient,
    YouTubeClient,
    add_link,
    diff_live,
    ended_embed,
    link_key,
    live_embed,
    load_links,
    load_state,
    parse_twitch,
    parse_youtube,
    remove_link,
    save_links,
    save_state,
)
from ..util import get_channel, get_role, is_staff, send_log

log = logging.getLogger("quartermaster.streams")

TWITCH_POLL_SECONDS = 60
YOUTUBE_EVERY_N_POLLS = 2   # YouTube is checked every 2nd poll to stay well inside the free quota
PLATFORM_CHOICES = [
    app_commands.Choice(name="Twitch", value=TWITCH),
    app_commands.Choice(name="YouTube", value=YOUTUBE),
]


class Streams(commands.Cog):
    stream = app_commands.Group(name="stream", description="Go-live alerts for Twitch and YouTube", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.twitch: Optional[TwitchClient] = None
        self.youtube: Optional[YouTubeClient] = None
        self._ticks = 0

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        tid = os.getenv("TWITCH_CLIENT_ID", "").strip()
        tsecret = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
        ykey = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.twitch = TwitchClient(self.session, tid, tsecret) if tid and tsecret else None
        self.youtube = YouTubeClient(self.session, ykey) if ykey else None
        if self.twitch or self.youtube:
            self.poll.start()
        else:
            log.info("No Twitch or YouTube keys set, so stream alerts are switched off")

    async def cog_unload(self):
        self.poll.cancel()
        if self.session:
            await self.session.close()

    # ---- the polling loop ---------------------------------------------------------------------------------

    @tasks.loop(seconds=TWITCH_POLL_SECONDS)
    async def poll(self):
        self._ticks += 1
        for guild in list(self.bot.guilds):
            try:
                await self._poll_guild(guild, youtube_due=self._ticks % YOUTUBE_EVERY_N_POLLS == 0)
            except Exception:  # one server's problem must not stop the loop
                log.exception("Stream poll failed for guild %s", guild.id)

    @poll.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    async def _poll_guild(self, guild: discord.Guild, youtube_due: bool):
        settings = self.bot.settings
        links = load_links(settings, guild.id)
        state = load_state(settings, guild.id)
        if not links and not state:
            return
        by_key = {link_key(l["platform"], l["channel_id"]): l for l in links}
        live_now: dict = {}
        polled: set[str] = set(k for k in state if k not in by_key)  # links that were removed: let them end

        twitch_links = [l for l in links if l["platform"] == TWITCH]
        if twitch_links and self.twitch:
            games = {l["channel_id"]: l.get("game", "") for l in twitch_links}
            try:
                streams = await self.twitch.get_streams([l["channel_id"] for l in twitch_links], games)
            except StreamAPIError as exc:
                log.warning("Twitch poll failed: %s", exc)
            except aiohttp.ClientError as exc:
                log.warning("Twitch poll failed: %s", exc)
            else:
                live_now.update({s.key: s for s in streams})
                polled.update(link_key(TWITCH, l["channel_id"]) for l in twitch_links)

        youtube_links = [l for l in links if l["platform"] == YOUTUBE]
        if youtube_links and self.youtube and youtube_due:
            try:
                streams = await self.youtube.live_now([l["channel_id"] for l in youtube_links])
            except (StreamAPIError, aiohttp.ClientError) as exc:
                log.warning("YouTube poll failed: %s", exc)
            else:
                live_now.update({s.key: s for s in streams})
                polled.update(link_key(YOUTUBE, l["channel_id"]) for l in youtube_links)

        new_state, actions = diff_live(state, live_now, polled, time.time())
        for action, key in actions:
            link = by_key.get(key)
            try:
                if action == "end":
                    await self._end(guild, new_state[key])
                elif link is None:
                    new_state[key]["live"] = False   # link vanished between polls; nothing to announce
                else:
                    await self._announce(guild, link, live_now[key], new_state[key], resume=action == "resume")
            except discord.HTTPException as exc:
                log.warning("Couldn't update the stream post for %s: %s", key, exc)
        if new_state != state:
            save_state(settings, guild.id, new_state)

    async def _announce(self, guild, link, stream, entry: dict, resume: bool):
        member = guild.get_member(link["user_id"])
        if member is None:
            entry["live"] = False
            return
        channel = get_channel(self.bot, guild, "streams_clips")
        if channel is None:
            log.warning("No #streams-n-clips channel is set up in guild %s; run /setup run", guild.id)
            return
        embed = live_embed(stream, member.display_name, member.display_avatar.url)
        if resume and entry.get("message_id"):
            try:
                message = await channel.fetch_message(entry["message_id"])
                await message.edit(embed=embed)
                return
            except discord.NotFound:
                pass  # the old post is gone; fall through and post a fresh one
        role = get_role(self.bot, guild, ROLE_STREAMS)
        ping = role if role is not None and role.mentionable else None
        content = f"{ping.mention} **{member.display_name}** just went live!" if ping else None
        message = await channel.send(
            content=content, embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=[ping] if ping else False, users=False, everyone=False),
        )
        entry["message_id"] = message.id

    async def _end(self, guild, entry: dict):
        channel = get_channel(self.bot, guild, "streams_clips")
        if channel is None or not entry.get("message_id"):
            return
        try:
            message = await channel.fetch_message(entry["message_id"])
        except discord.NotFound:
            return
        if message.embeds:
            await message.edit(content=None, embed=ended_embed(message.embeds[0]))

    # ---- commands -----------------------------------------------------------------------------------------

    @stream.command(name="link", description="Link your Twitch or YouTube channel so the server hears when you go live")
    @app_commands.describe(
        platform="Where you stream",
        channel="Your Twitch name, or your YouTube @handle, channel link or channel ID",
        game="Game to show on YouTube alerts (Twitch fills this in itself)",
        member="Staff only: link a channel for someone else",
    )
    @app_commands.choices(platform=PLATFORM_CHOICES)
    async def link(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        channel: app_commands.Range[str, 2, 200],
        game: Optional[app_commands.Range[str, 1, 60]] = None,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        if target.id != interaction.user.id and not is_staff(self.bot, interaction.user):
            return await interaction.followup.send("Only staff can link a channel for someone else.", ephemeral=True)
        if target.bot:
            return await interaction.followup.send("Bots don't stream.", ephemeral=True)

        try:
            if platform.value == TWITCH:
                if self.twitch is None:
                    return await interaction.followup.send("Twitch alerts aren't switched on yet. Ask an admin.", ephemeral=True)
                login = parse_twitch(channel)
                if login is None:
                    return await interaction.followup.send("That doesn't look like a Twitch name or link.", ephemeral=True)
                users = await self.twitch.get_users([login])
                if login not in users:
                    return await interaction.followup.send(f"I couldn't find a Twitch channel called `{login}`.", ephemeral=True)
                channel_id, name = login, users[login].get("display_name") or login
            else:
                if self.youtube is None:
                    return await interaction.followup.send("YouTube alerts aren't switched on yet. Ask an admin.", ephemeral=True)
                ref = parse_youtube(channel)
                if ref is None:
                    return await interaction.followup.send(
                        "Use your YouTube `@handle`, a `youtube.com/@handle` or `youtube.com/channel/UC...` link, "
                        "or the channel ID. Old `/c/` and `/user/` links don't work.", ephemeral=True,
                    )
                found = await self.youtube.resolve(ref)
                if found is None:
                    return await interaction.followup.send("I couldn't find that YouTube channel.", ephemeral=True)
                channel_id, name = found["channel_id"], found["name"]
        except (StreamAPIError, aiohttp.ClientError) as exc:
            log.warning("Link lookup failed: %s", exc)
            return await interaction.followup.send("I couldn't reach the platform just now. Try again in a minute.", ephemeral=True)

        links, taken_by = add_link(
            load_links(self.bot.settings, interaction.guild.id), target.id, platform.value, channel_id, name, (game or "").strip()
        )
        if taken_by is not None:
            return await interaction.followup.send(f"That channel is already linked to <@{taken_by}>.", ephemeral=True)
        save_links(self.bot.settings, interaction.guild.id, links)

        label = PLATFORM_LABEL[platform.value]
        where = get_channel(self.bot, interaction.guild, "streams_clips")
        role = get_role(self.bot, interaction.guild, ROLE_STREAMS)
        lines = [f"Linked **{name}** on {label} to {target.mention}."]
        lines.append(f"When you go live I'll post in {where.mention}." if where else "Ask an admin to run `/setup run` so I know where to post.")
        if role:
            lines.append(f"Members who want the alerts can pick **{role.name}** in the role picker.")
        await interaction.followup.send("\n".join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        await send_log(self.bot, interaction.guild, f"🔴 {interaction.user.mention} linked {label} `{channel_id}` for {target.mention}.")

    @stream.command(name="unlink", description="Remove a linked Twitch or YouTube channel")
    @app_commands.describe(platform="Which one to remove", member="Staff only: remove someone else's link")
    @app_commands.choices(platform=PLATFORM_CHOICES)
    async def unlink(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        member: Optional[discord.Member] = None,
    ):
        target = member or interaction.user
        if target.id != interaction.user.id and not is_staff(self.bot, interaction.user):
            return await interaction.response.send_message("Only staff can remove someone else's link.", ephemeral=True)
        links, removed = remove_link(load_links(self.bot.settings, interaction.guild.id), target.id, platform.value)
        if not removed:
            return await interaction.response.send_message(
                f"No {PLATFORM_LABEL[platform.value]} channel is linked for {target.mention}.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        save_links(self.bot.settings, interaction.guild.id, links)
        await interaction.response.send_message(
            f"Removed the {PLATFORM_LABEL[platform.value]} link for {target.mention}.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @stream.command(name="list", description="See who is linked for go-live alerts")
    async def list_links(self, interaction: discord.Interaction):
        links = load_links(self.bot.settings, interaction.guild.id)
        if not links:
            return await interaction.response.send_message("Nobody is linked yet. Use `/stream link`.", ephemeral=True)
        lines = [
            f"<@{l['user_id']}>: {PLATFORM_LABEL[l['platform']]} **{l['name']}**" + (f" ({l['game']})" if l.get("game") else "")
            for l in sorted(links, key=lambda l: (l["user_id"], l["platform"]))
        ]
        await interaction.response.send_message(
            "\n".join(lines)[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @stream.command(name="status", description="Staff: check that stream alerts are set up")
    async def status(self, interaction: discord.Interaction):
        if not is_staff(self.bot, interaction.user):
            return await interaction.response.send_message("Only staff can check this.", ephemeral=True)
        guild = interaction.guild
        where = get_channel(self.bot, guild, "streams_clips")
        role = get_role(self.bot, guild, ROLE_STREAMS)
        links = load_links(self.bot.settings, guild.id)
        lines = [
            f"Twitch: {'on' if self.twitch else 'off (set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET)'}",
            f"YouTube: {'on' if self.youtube else 'off (set YOUTUBE_API_KEY)'}",
            f"Alerts go to: {where.mention if where else 'not set, run /setup run'}",
            f"Ping role: {role.mention if role else 'not created, run /setup run'}",
            f"Linked channels: {len(links)}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Streams(bot))
