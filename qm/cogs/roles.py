"""Role-picker: registers the persistent buttons and lets admins repost the picker."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..views import RolePickerView, post_picker


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Persistent view: the buttons keep working after a restart.
        self.bot.add_view(RolePickerView())

    @app_commands.command(name="rolepicker", description="Post the role-picker in this channel")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def rolepicker(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Use this in a text channel.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await post_picker(self.bot, interaction.channel)
        await interaction.followup.send("Posted.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Roles(bot))
