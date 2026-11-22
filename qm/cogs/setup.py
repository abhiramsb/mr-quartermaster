"""/setup run, /setup migrate and /setup status (administrators only)."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..builder import build
from ..layout import ROLE_CAPTAIN, ROLE_CLUB, ROLE_RECRUIT, ROLE_SPECS, ROLE_SQUAD
from ..util import chunk_lines, get_channel, get_role
from ..views import post_picker


async def _reply_chunks(interaction: discord.Interaction, header: str, lines: list[str]) -> None:
    chunks = chunk_lines(lines)
    first = True
    for chunk in chunks or ["Nothing to report."]:
        text = f"{header}\n{chunk}" if first else chunk
        await interaction.followup.send(text, ephemeral=True)
        first = False


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    setup = app_commands.Group(
        name="setup",
        description="Build and maintain the server layout",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @setup.command(name="run", description="Create or update roles, channels and permissions (preview by default)")
    @app_commands.describe(dry_run="True shows what would change without changing anything")
    @app_commands.checks.has_permissions(administrator=True)
    async def run(self, interaction: discord.Interaction, dry_run: bool = True):
        guild = interaction.guild
        me = guild.me.guild_permissions
        if not dry_run and not (me.manage_roles and me.manage_channels):
            return await interaction.response.send_message(
                "I need **Manage Roles** and **Manage Channels** first. Fix my role permissions and try again.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        log = await build(self.bot, guild, dry_run)

        if not dry_run:
            picker_channel = get_channel(self.bot, guild, "pick_roles")
            stored = self.bot.settings.get_int(guild.id, "picker_message")
            exists = False
            if picker_channel is not None and stored:
                try:
                    await picker_channel.fetch_message(stored)
                    exists = True
                except discord.HTTPException:
                    exists = False
            if picker_channel is not None and not exists:
                await post_picker(self.bot, picker_channel)
                log.append("📌 posted the role-picker in #pick-your-roles")
            log.append("")
            log.append("ℹ Admin and Mod roles (if I created them) have no special permissions. Set those yourself, "
                       "and keep them above my role.")

        header = "**Preview only. Nothing was changed.** Run again with `dry_run: False` to apply." if dry_run else "**Done.**"
        await _reply_chunks(interaction, header, log)

    @setup.command(name="migrate", description="Give existing members the new roles (preview by default)")
    @app_commands.describe(
        dry_run="True shows what would change without changing anything",
        give_recruit_to_all="Give Recruit to every member who doesn't have it",
        captain_from="Old role whose holders become MRFC Captain (also Squad and Football Club)",
        squad_from="Old role whose holders become MRFC Squad (also Football Club)",
        club_from="Old role whose holders become Football Club",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def migrate(
        self,
        interaction: discord.Interaction,
        dry_run: bool = True,
        give_recruit_to_all: bool = True,
        captain_from: Optional[discord.Role] = None,
        squad_from: Optional[discord.Role] = None,
        club_from: Optional[discord.Role] = None,
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)
        if not guild.chunked:
            await guild.chunk()

        recruit = get_role(self.bot, guild, ROLE_RECRUIT)
        captain = get_role(self.bot, guild, ROLE_CAPTAIN)
        squad = get_role(self.bot, guild, ROLE_SQUAD)
        club = get_role(self.bot, guild, ROLE_CLUB)
        needed = {"Recruit": recruit, "MRFC Captain": captain, "MRFC Squad": squad, "Football Club": club}
        missing = [name for name, role in needed.items() if role is None]
        if missing:
            return await interaction.followup.send(
                f"These roles don't exist yet: {', '.join(missing)}. Run `/setup run` first.", ephemeral=True
            )
        blocked = [r.name for r in needed.values() if not r.is_assignable()]
        if blocked:
            return await interaction.followup.send(
                f"I can't assign: {', '.join(blocked)}. Move my role above them and try again.", ephemeral=True
            )

        plan: dict[discord.Member, list[discord.Role]] = {}
        for member in guild.members:
            if member.bot:
                continue
            wanted: list[discord.Role] = []
            if give_recruit_to_all:
                wanted.append(recruit)
            if captain_from and captain_from in member.roles:
                wanted += [captain, squad, club]
            elif squad_from and squad_from in member.roles:
                wanted += [squad, club]
            if club_from and club_from in member.roles:
                wanted.append(club)
            to_add = [r for r in dict.fromkeys(wanted) if r not in member.roles]
            if to_add:
                plan[member] = to_add

        lines = [f"{m.display_name}: + {', '.join(r.name for r in roles)}" for m, roles in plan.items()]
        if not dry_run:
            failed = 0
            for member, roles in plan.items():
                try:
                    await member.add_roles(*roles, reason="MR_Quartermaster /setup migrate")
                except discord.HTTPException:
                    failed += 1
            if failed:
                lines.append(f"⚠ {failed} member(s) could not be updated.")
        header = (f"**Preview only.** {len(plan)} member(s) would change:" if dry_run
                  else f"**Done.** Updated {len(plan)} member(s):")
        await _reply_chunks(interaction, header, lines or ["Nobody needs changes."])

    @setup.command(name="status", description="Check what is configured and what needs fixing")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        guild = interaction.guild
        me = guild.me.guild_permissions
        lines = [
            f"{'✅' if me.manage_roles else '❌'} Manage Roles",
            f"{'✅' if me.manage_channels else '❌'} Manage Channels",
            "",
            "**Roles**",
        ]
        for spec in ROLE_SPECS:
            role = get_role(self.bot, guild, spec.name)
            if role is None:
                lines.append(f"❌ {spec.name}: missing")
            elif spec.managed and not role.is_assignable():
                lines.append(f"⚠ {spec.name}: above my role, so I can't assign it")
            else:
                lines.append(f"✅ {spec.name}")
        lines += ["", "**Channels**"]
        for key in ("reception", "pick_roles", "bot_logs", "mrfc_sessions", "mrfc_tactics", "mrfc_scouting"):
            channel = get_channel(self.bot, guild, key)
            lines.append(f"{'✅' if channel else '❌'} {channel.mention if channel else key}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Setup(bot))
