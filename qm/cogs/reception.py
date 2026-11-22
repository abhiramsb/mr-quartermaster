"""#reception: random welcome on join, random send-off on exit, the Recruit role, and curated lines and GIFs."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from ..layout import ROLE_RECRUIT
from ..messages import (
    KINDS,
    MAX_CUSTOM_ITEMS,
    MAX_LINE_LENGTH,
    cooldown_ok,
    get_items,
    gif_items,
    pick_gif,
    pick_line,
    render,
    save_items,
    send_embed,
    valid_gif_url,
    values_for,
)
from ..util import get_channel, get_role

KIND_CHOICES = [app_commands.Choice(name=k.label, value=k.key) for k in KINDS.values()]


class Reception(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
        values = values_for(self.bot, guild, member)
        line = render(pick_line(self.bot, guild.id, "welcome"), values)
        embed = discord.Embed(
            title="A new recruit has arrived",
            description=f"{line}\n\nPick your roles in {values['picker']}.",
            colour=discord.Colour.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await send_embed(channel, embed, pick_gif(self.bot, guild.id, "welcome"),
                             discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """When a member welcomes a newcomer in #reception (replying to the welcome post, or mentioning someone
        who joined in the last two days), reply with a line and a GIF. Needs no Message Content intent."""
        guild = message.guild
        if guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        channel = get_channel(self.bot, guild, "reception")
        if channel is None or message.channel.id != channel.id:
            return
        newcomer = None
        ref = message.reference.resolved if message.reference else None
        if isinstance(ref, discord.Message) and ref.author.id == self.bot.user.id:
            newcomer = next((m for m in ref.mentions if not m.bot and m.id != message.author.id), None)
        if newcomer is None:
            now = discord.utils.utcnow()
            newcomer = next((m for m in message.mentions
                             if isinstance(m, discord.Member) and not m.bot and m.id != message.author.id
                             and m.joined_at and (now - m.joined_at).days < 2), None)
        if newcomer is None:
            return
        if not cooldown_ok(self.bot, guild.id, "greet", message.author.id, time.time()):
            return
        values = values_for(self.bot, guild, message.author)
        values["new"] = newcomer.display_name
        embed = discord.Embed(description=render(pick_line(self.bot, guild.id, "greet"), values),
                              colour=discord.Colour.gold())
        try:
            await send_embed(message.channel, embed, pick_gif(self.bot, guild.id, "greet"),
                             discord.AllowedMentions(users=[message.author]))
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
        line = render(pick_line(self.bot, guild.id, "farewell"), values_for(self.bot, guild, member))
        embed = discord.Embed(description=line, colour=discord.Colour.dark_grey())
        try:
            await send_embed(channel, embed, pick_gif(self.bot, guild.id, "farewell"),
                             discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    # ---- admin commands ----
    reception = app_commands.Group(
        name="reception",
        description="Manage the welcome and send-off messages",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )
    line = app_commands.Group(name="line", description="Extra message lines", parent=reception)
    gif = app_commands.Group(name="gif", description="Curated GIF list", parent=reception)

    @line.command(name="add", description="Add a line to a message pool. Use {user} {name} {server} {count}")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def line_add(self, interaction: discord.Interaction, kind: app_commands.Choice[str],
                       text: app_commands.Range[str, 1, MAX_LINE_LENGTH]):
        items = get_items(self.bot, interaction.guild_id, "lines", kind.value)
        if len(items) >= MAX_CUSTOM_ITEMS:
            return await interaction.response.send_message(f"That list is full ({MAX_CUSTOM_ITEMS} lines).", ephemeral=True)
        items.append(text)
        save_items(self.bot, interaction.guild_id, "lines", kind.value, items)
        await interaction.response.send_message(f"Added to **{kind.name}**. It now has {len(items)} custom line(s).", ephemeral=True)

    @line.command(name="list", description="Show the custom lines for a message pool")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def line_list(self, interaction: discord.Interaction, kind: app_commands.Choice[str]):
        items = get_items(self.bot, interaction.guild_id, "lines", kind.value)
        built_in = len(KINDS[kind.value].builtin)
        body = "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)) or "None yet."
        await interaction.response.send_message(
            f"**{kind.name}**: {built_in} built-in line(s) plus your custom ones:\n{body}"[:1900],
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @line.command(name="remove", description="Remove a custom line by its number from /reception line list")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def line_remove(self, interaction: discord.Interaction, kind: app_commands.Choice[str], number: int):
        items = get_items(self.bot, interaction.guild_id, "lines", kind.value)
        if not 1 <= number <= len(items):
            return await interaction.response.send_message("No custom line with that number.", ephemeral=True)
        removed = items.pop(number - 1)
        save_items(self.bot, interaction.guild_id, "lines", kind.value, items)
        await interaction.response.send_message(f"Removed: {removed}", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @gif.command(name="add", description="Add a GIF link (https) to a message pool")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def gif_add(self, interaction: discord.Interaction, kind: app_commands.Choice[str], url: str):
        url = url.strip()
        if not valid_gif_url(url):
            return await interaction.response.send_message("That needs to be a full https:// link.", ephemeral=True)
        items = gif_items(self.bot, interaction.guild_id, kind.value)
        if url in items:
            return await interaction.response.send_message("That GIF is already in the list.", ephemeral=True)
        if len(items) >= MAX_CUSTOM_ITEMS:
            return await interaction.response.send_message(f"That list is full ({MAX_CUSTOM_ITEMS} GIFs).", ephemeral=True)
        items.append(url)
        save_items(self.bot, interaction.guild_id, "gifs", kind.value, items)
        await interaction.response.send_message(f"Added to **{kind.name}**. It now has {len(items)} GIF(s).", ephemeral=True)

    @gif.command(name="list", description="Show the GIFs for a message pool")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def gif_list(self, interaction: discord.Interaction, kind: app_commands.Choice[str]):
        items = gif_items(self.bot, interaction.guild_id, kind.value)
        body = "\n".join(f"{i}. <{u}>" for i, u in enumerate(items, 1)) or "None yet. No GIF is shown until you add some."
        await interaction.response.send_message(f"**{kind.name}** GIFs:\n{body}"[:1900], ephemeral=True)

    @gif.command(name="remove", description="Remove a GIF by its number from /reception gif list")
    @app_commands.choices(kind=KIND_CHOICES)
    @app_commands.checks.has_permissions(administrator=True)
    async def gif_remove(self, interaction: discord.Interaction, kind: app_commands.Choice[str], number: int):
        items = gif_items(self.bot, interaction.guild_id, kind.value)
        if not 1 <= number <= len(items):
            return await interaction.response.send_message("No GIF with that number.", ephemeral=True)
        removed = items.pop(number - 1)
        save_items(self.bot, interaction.guild_id, "gifs", kind.value, items)
        await interaction.response.send_message(f"Removed <{removed}>.", ephemeral=True)

    @reception.command(name="preview", description="Show a random sample of each message (only you see this)")
    @app_commands.checks.has_permissions(administrator=True)
    async def preview(self, interaction: discord.Interaction):
        guild = interaction.guild
        values = values_for(self.bot, guild, interaction.user)
        parts = []
        for kind in KINDS.values():
            gifs = len(gif_items(self.bot, guild.id, kind.key))
            parts.append(f"**{kind.label}** ({gifs} GIF(s))\n{render(pick_line(self.bot, guild.id, kind.key), values)}")
        await interaction.response.send_message("\n\n".join(parts), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Reception(bot))
