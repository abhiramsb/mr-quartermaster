"""/squad: lets MRFC Captains manage the Squad role without needing Manage Roles themselves."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..layout import ROLE_CAPTAIN, ROLE_CLUB, ROLE_SQUAD
from ..util import get_role, has_role, is_admin, is_captain, send_log


class Squad(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    squad = app_commands.Group(name="squad", description="Manage the MRFC Squad", guild_only=True)

    async def _check(self, interaction: discord.Interaction, member: discord.Member):
        """Return (squad_role, club_role) or send an error and return None."""
        if not is_captain(self.bot, interaction.user):
            await interaction.response.send_message("Only MRFC Captains can do this.", ephemeral=True)
            return None
        if member.bot:
            await interaction.response.send_message("Bots can't join the squad.", ephemeral=True)
            return None
        if has_role(self.bot, member, ROLE_CAPTAIN) and not is_admin(interaction.user):
            await interaction.response.send_message("Captains are managed by the server admins.", ephemeral=True)
            return None
        squad_role = get_role(self.bot, interaction.guild, ROLE_SQUAD)
        club_role = get_role(self.bot, interaction.guild, ROLE_CLUB)
        if squad_role is None or club_role is None:
            await interaction.response.send_message("The roles aren't set up yet. An admin needs to run `/setup run`.", ephemeral=True)
            return None
        if not (squad_role.is_assignable() and club_role.is_assignable()):
            await interaction.response.send_message("I can't assign those roles yet. An admin needs to move my role above them.", ephemeral=True)
            return None
        return squad_role, club_role

    @squad.command(name="add", description="Add a member to the MRFC Squad")
    async def add(self, interaction: discord.Interaction, member: discord.Member):
        roles = await self._check(interaction, member)
        if roles is None:
            return
        squad_role, club_role = roles
        await interaction.response.defer(ephemeral=True)
        await member.add_roles(squad_role, club_role, reason=f"/squad add by {interaction.user}")
        await send_log(self.bot, interaction.guild,
                       f"🟢 {interaction.user.mention} added {member.mention} to **{squad_role.name}**.")
        await interaction.followup.send(f"{member.mention} is now in the squad.", ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @squad.command(name="remove", description="Remove a member from the MRFC Squad (they keep Football Club)")
    async def remove(self, interaction: discord.Interaction, member: discord.Member):
        roles = await self._check(interaction, member)
        if roles is None:
            return
        squad_role, _ = roles
        await interaction.response.defer(ephemeral=True)
        await member.remove_roles(squad_role, reason=f"/squad remove by {interaction.user}")
        await send_log(self.bot, interaction.guild,
                       f"🔴 {interaction.user.mention} removed {member.mention} from **{squad_role.name}**.")
        await interaction.followup.send(f"{member.mention} is no longer in the squad.", ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @squad.command(name="list", description="Show the Captains and Squad")
    async def list_(self, interaction: discord.Interaction):
        guild = interaction.guild
        captain = get_role(self.bot, guild, ROLE_CAPTAIN)
        squad_role = get_role(self.bot, guild, ROLE_SQUAD)
        captains = [m.display_name for m in (captain.members if captain else [])]
        players = [m.display_name for m in (squad_role.members if squad_role else []) if captain not in m.roles]
        embed = discord.Embed(title="MRFC Squad", colour=discord.Colour.gold())
        embed.add_field(name=f"Captains ({len(captains)})", value="\n".join(captains) or "None yet", inline=False)
        embed.add_field(name=f"Squad ({len(players)})", value="\n".join(players) or "None yet", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Squad(bot))
