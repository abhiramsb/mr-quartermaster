"""/announce: staff post a clean announcement embed, optionally pinging a role."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..util import get_channel, is_staff, send_log


class Announce(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="announce", description="Post an announcement")
    @app_commands.guild_only()
    @app_commands.describe(
        title="Headline",
        message="The announcement text",
        channel="Where to post (default: #announcements)",
        ping="Role to ping",
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        title: app_commands.Range[str, 1, 200],
        message: app_commands.Range[str, 1, 3500],
        channel: Optional[discord.TextChannel] = None,
        ping: Optional[discord.Role] = None,
    ):
        if not is_staff(self.bot, interaction.user):
            return await interaction.response.send_message("Only staff can post announcements.", ephemeral=True)
        target = channel or get_channel(self.bot, interaction.guild, "announcements")
        if target is None:
            return await interaction.response.send_message(
                "I don't know where `#announcements` is. Run `/setup run` or pick a channel.", ephemeral=True
            )
        # Pinging @everyone or an unmentionable role is only allowed for people who could do it themselves.
        if ping is not None and not (ping.mentionable or interaction.user.guild_permissions.mention_everyone):
            return await interaction.response.send_message("That role can't be pinged.", ephemeral=True)

        embed = discord.Embed(title=title, description=message, colour=discord.Colour.blurple())
        embed.set_footer(text=f"Posted by {interaction.user.display_name}")
        await interaction.response.defer(ephemeral=True)
        try:
            await target.send(
                content=ping.mention if ping else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=[ping] if ping else False),
            )
        except discord.HTTPException:
            return await interaction.followup.send("I couldn't post there. Check my permissions in that channel.", ephemeral=True)
        await send_log(self.bot, interaction.guild, f"📢 {interaction.user.mention} posted an announcement in {target.mention}: **{title}**")
        await interaction.followup.send(f"Posted in {target.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Announce(bot))
