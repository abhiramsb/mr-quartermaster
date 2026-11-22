"""The role-picker: persistent buttons that toggle self-assignable roles."""
from __future__ import annotations

import discord

from .layout import ROLE_CAPTAIN, ROLE_CLUB, ROLE_EVENTS, ROLE_NEWS, ROLE_SQUAD, ROLE_STREAMS
from .messages import game_leave, game_welcome
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
