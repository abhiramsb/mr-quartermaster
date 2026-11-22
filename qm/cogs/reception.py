"""#reception: welcome on join, send-off on exit, and the default Recruit role."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..layout import ROLE_RECRUIT
from ..util import get_channel, get_role

DEFAULT_WELCOME = (
    "Welcome to **{server}**, {user}! You're member #{count}.\n"
    "Head to {picker} to choose your roles."
)
DEFAULT_FAREWELL = "👋 **{name}** has left {server}. We're now {count} strong."


def render(template: str, *, member: discord.abc.User, guild: discord.Guild, picker: str) -> str:
    """Fill in {user}, {name}, {server}, {count} and {picker}. Unknown placeholders are left as typed."""
    values = {
        "{user}": member.mention,
        "{name}": member.display_name,
        "{server}": guild.name,
        "{count}": str(guild.member_count or 0),
        "{picker}": picker,
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template


class Reception(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _picker_mention(self, guild: discord.Guild) -> str:
        channel = get_channel(self.bot, guild, "pick_roles")
        return channel.mention if channel else "#pick-your-roles"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        recruit = get_role(self.bot, guild, ROLE_RECRUIT)
        if recruit is not None and recruit.is_assignable():
            try:
                await member.add_roles(recruit, reason="Autorole on join")
            except discord.HTTPException:
                pass
        channel = get_channel(self.bot, guild, "reception")
        if channel is None:
            return
        template = self.bot.settings.get(guild.id, "welcome_text", DEFAULT_WELCOME)
        embed = discord.Embed(
            title="A new recruit has arrived",
            description=render(template, member=member, guild=guild, picker=self._picker_mention(guild)),
            colour=discord.Colour.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        channel = get_channel(self.bot, guild, "reception")
        if channel is None:
            return
        template = self.bot.settings.get(guild.id, "farewell_text", DEFAULT_FAREWELL)
        text = render(template, member=member, guild=guild, picker=self._picker_mention(guild))
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    reception = app_commands.Group(
        name="reception",
        description="Customise the join and leave messages",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @reception.command(name="welcome", description="Set the welcome text. Use {user} {name} {server} {count} {picker}")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 1000]):
        self.bot.settings.set(interaction.guild_id, "welcome_text", text)
        await interaction.response.send_message("Welcome text saved. Try `/reception preview`.", ephemeral=True)

    @reception.command(name="farewell", description="Set the send-off text. Use {user} {name} {server} {count}")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_farewell(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 1000]):
        self.bot.settings.set(interaction.guild_id, "farewell_text", text)
        await interaction.response.send_message("Send-off text saved. Try `/reception preview`.", ephemeral=True)

    @reception.command(name="preview", description="Show how the welcome and send-off will look (only you see this)")
    @app_commands.checks.has_permissions(administrator=True)
    async def preview(self, interaction: discord.Interaction):
        guild = interaction.guild
        picker = self._picker_mention(guild)
        welcome = render(self.bot.settings.get(guild.id, "welcome_text", DEFAULT_WELCOME),
                         member=interaction.user, guild=guild, picker=picker)
        farewell = render(self.bot.settings.get(guild.id, "farewell_text", DEFAULT_FAREWELL),
                          member=interaction.user, guild=guild, picker=picker)
        await interaction.response.send_message(
            f"**Welcome**\n{welcome}\n\n**Send-off**\n{farewell}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot):
    await bot.add_cog(Reception(bot))
