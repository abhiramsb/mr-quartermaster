"""The role-picker: persistent buttons that toggle self-assignable roles."""
from __future__ import annotations

import discord

from .layout import ROLE_CAPTAIN, ROLE_CLUB, ROLE_EVENTS, ROLE_NEWS, ROLE_SQUAD, ROLE_STREAMS
import json
import re

from .messages import game_leave, game_welcome, pick_gif, pick_line, render, send_embed, values_for
from .util import get_role, has_role, slug

# (role name, label, emoji, style)
PICKER_ROLES = (
    (ROLE_CLUB, "Football Club", "⚽", discord.ButtonStyle.primary),
    (ROLE_EVENTS, "Event Pings", "📣", discord.ButtonStyle.secondary),
    (ROLE_NEWS, "News Pings", "📰", discord.ButtonStyle.secondary),
    (ROLE_STREAMS, "Stream Pings", "🔴", discord.ButtonStyle.secondary),
)


def roles_status(bot, guild: discord.Guild, member: discord.Member) -> str:
    """One line per picker role: ✅ if the member has it, ⬜ if not."""
    lines = []
    for role_name, label, emoji, _style in PICKER_ROLES:
        role = get_role(bot, guild, role_name)
        has = role is not None and role in member.roles
        lines.append(f"{'✅' if has else '⬜'} {emoji} {label}")
    return "\n".join(lines)


async def toggle_role(interaction: discord.Interaction, role_name: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot, guild, member = interaction.client, interaction.guild, interaction.user
    role = get_role(bot, guild, role_name)
    if role is None:
        return await interaction.followup.send(
            "That role isn't set up yet. Ask an admin to run `/setup run`.", ephemeral=True
        )
    if not role.is_assignable():
        return await interaction.followup.send(
            "I can't hand out that role yet. An admin needs to move my role above it.", ephemeral=True
        )

    if role in member.roles:
        if role_name == ROLE_CLUB and (has_role(bot, member, ROLE_SQUAD) or has_role(bot, member, ROLE_CAPTAIN)):
            return await interaction.followup.send(
                "You're in the squad, so you keep Football Club. Ask a Captain if you want to step down.",
                ephemeral=True,
            )
        await member.remove_roles(role, reason="Role picker")
        await interaction.followup.send(
            f"Removed **{role.name}**.\n\n**Your roles now**\n{roles_status(bot, guild, member)}", ephemeral=True
        )
        await game_leave(bot, guild, member, role_name)
        return

    await member.add_roles(role, reason="Role picker")
    extra = " The MRFC section is now unlocked." if role_name == ROLE_CLUB else ""
    await interaction.followup.send(
        f"You now have **{role.name}**.{extra}\n\n**Your roles now**\n{roles_status(bot, guild, member)}",
        ephemeral=True,
    )
    # The game-specific welcome follows the pick.
    await game_welcome(bot, guild, member, role_name)


class RoleButton(discord.ui.Button):
    def __init__(self, role_name: str, label: str, emoji: str, style: discord.ButtonStyle):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=f"qm:role:{slug(role_name)}")
        self.role_name = role_name

    async def callback(self, interaction: discord.Interaction) -> None:
        await toggle_role(interaction, self.role_name)


class MyRolesButton(discord.ui.Button):
    """Shows the member which picker roles they currently have (the buttons themselves look the same for everyone)."""

    def __init__(self):
        super().__init__(label="My roles", emoji="📋", style=discord.ButtonStyle.success, custom_id="qm:role:mine")

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"**Your roles**\n{roles_status(interaction.client, interaction.guild, interaction.user)}", ephemeral=True
        )


class RolePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for role_name, label, emoji, style in PICKER_ROLES:
            self.add_item(RoleButton(role_name, label, emoji, style))
        self.add_item(MyRolesButton())


def picker_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Pick your roles",
        description=(
            "Press a button to add a role. Press it again to remove it.\n\n"
            "⚽ **Football Club**: unlocks the MRFC section (sessions, chat and more).\n"
            "📣 **Event Pings**: get pinged for events.\n"
            "📰 **News Pings**: get pinged for server news.\n"
            "🔴 **Stream Pings**: get pinged when someone goes live.\n\n"
            "📋 **My roles** shows which ones you have right now."
        ),
        colour=discord.Colour.blurple(),
    )
    return embed


async def post_picker(bot, channel: discord.TextChannel) -> discord.Message:
    message = await channel.send(embed=picker_embed(), view=RolePickerView())
    bot.settings.set(channel.guild.id, "picker_message", message.id)
    return message


# ---- the "Welcome" button under a new recruit's post in #reception ----

def welcome_label(count: int) -> str:
    return "Welcome" if count <= 0 else f"Welcome ({count})"


class WelcomeButton(discord.ui.DynamicItem[discord.ui.Button], template=r"qm:welcome:(?P<id>[0-9]+)"):
    """One click welcomes the newcomer: posts a line and a GIF as a reply. The newcomer's id lives in the custom_id,
    so the button keeps working after a restart."""

    def __init__(self, newcomer_id: int, count: int = 0):
        super().__init__(discord.ui.Button(label=welcome_label(count), emoji="👋", style=discord.ButtonStyle.success,
                                           custom_id=f"qm:welcome:{newcomer_id}"))
        self.newcomer_id = newcomer_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        bot, guild = interaction.client, interaction.guild
        if guild is None:
            return
        newcomer = guild.get_member(self.newcomer_id)
        if newcomer is None:
            return await interaction.response.send_message("They've already left the server.", ephemeral=True)
        if interaction.user.id == newcomer.id:
            return await interaction.response.send_message("You can't welcome yourself, Recruit. 😄", ephemeral=True)
        key = f"welcomed:{newcomer.id}"
        try:
            greeters = [int(x) for x in json.loads(bot.settings.get(guild.id, key) or "[]")]
        except (ValueError, TypeError):
            greeters = []
        if interaction.user.id in greeters:
            return await interaction.response.send_message(f"You've already welcomed {newcomer.display_name}.", ephemeral=True)
        greeters.append(interaction.user.id)
        bot.settings.set(guild.id, key, json.dumps(greeters))
        # Reply publicly and update the count on the button.
        await interaction.response.edit_message(view=welcome_view(newcomer.id, len(greeters)))
        values = values_for(bot, guild, interaction.user)
        values["new"] = newcomer.mention
        embed = discord.Embed(description=render(pick_line(bot, guild.id, "greet"), values), colour=discord.Colour.gold())
        try:
            await send_embed(interaction.channel, embed, pick_gif(bot, guild.id, "greet"),
                             discord.AllowedMentions(users=[newcomer]), reference=interaction.message)
        except discord.HTTPException:
            pass


def welcome_view(newcomer_id: int, count: int = 0) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(WelcomeButton(newcomer_id, count))
    return view
