"""MR_Quartermaster: server-level bot for Millennial Regiment Gaming."""
from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from .db import Settings

log = logging.getLogger("quartermaster")

EXTENSIONS = (
    "qm.cogs.reception",
    "qm.cogs.roles",
    "qm.cogs.setup",
    "qm.cogs.squad",
    "qm.cogs.announce",
    "qm.cogs.logs",
    "qm.cogs.streams",
)


class Quartermaster(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # privileged: enable "Server Members Intent" in the Developer Portal
        # privileged: enable "Presence Intent" too, for go-live alerts from Discord's Streaming status.
        # Set PRESENCE_INTENT=0 to run without it (the bot refuses to start if it asks for an intent the portal hasn't enabled).
        intents.presences = os.getenv("PRESENCE_INTENT", "1").strip() != "0"
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.settings = Settings(os.getenv("DB_PATH", "quartermaster.db"))
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self):
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        dev_guild = os.getenv("DEV_GUILD_ID", "").strip()
        if dev_guild.isdigit():
            guild = discord.Object(id=int(dev_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to dev guild %s", dev_guild)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need to be a server administrator to use that."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You can't use that command here."
        else:
            log.exception("Command error", exc_info=error)
            message = "Something went wrong. Try again, and tell an admin if it keeps happening."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
