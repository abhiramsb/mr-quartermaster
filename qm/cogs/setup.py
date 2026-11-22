"""/setup run, /setup migrate and /setup status (administrators only)."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..builder import build
from ..layout import ROLE_CAPTAIN, ROLE_CLUB, ROLE_RECRUIT, ROLE_SPECS, ROLE_SQUAD
from ..messages import pick_gif, send_embed
from ..migrate import announcement_members, mention_blocks, plan_migration
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

    @setup.command(name="migrate", description="Give existing members their new roles (preview by default)")
    @app_commands.describe(
        dry_run="True shows what would change without changing anything",
        captain="Who becomes MRFC Captain (default: the server owner). Nobody else gets Captain or Squad",
        give_football_club_to_all="Give every existing member Football Club (with Recruit)",
        announce="Also post the relaunch announcement (#announcements) and the football welcome (#reception)",
        remove_old_role="An old role to remove from everyone once they have the new ones",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def migrate(
        self,
        interaction: discord.Interaction,
        dry_run: bool = True,
        captain: Optional[discord.Member] = None,
        give_football_club_to_all: bool = True,
        announce: bool = False,
        remove_old_role: Optional[discord.Role] = None,
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)
        if not guild.chunked:
            await guild.chunk()

        recruit = get_role(self.bot, guild, ROLE_RECRUIT)
        captain_role = get_role(self.bot, guild, ROLE_CAPTAIN)
        squad_role = get_role(self.bot, guild, ROLE_SQUAD)
        club = get_role(self.bot, guild, ROLE_CLUB)
        needed = {"Recruit": recruit, "MRFC Captain": captain_role, "MRFC Squad": squad_role, "Football Club": club}
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
        if remove_old_role is not None and (remove_old_role in needed.values() or not remove_old_role.is_assignable()):
            return await interaction.followup.send(
                "I can't remove that role (it's one of the new roles, or above my role).", ephemeral=True
            )

        captain_member = captain or guild.owner
        if captain_member is None:
            try:
                captain_member = await guild.fetch_member(guild.owner_id)
            except discord.HTTPException:
                captain_member = None
        if captain_member is None:
            return await interaction.followup.send("I couldn't work out who the Captain should be. Pick one with `captain`.", ephemeral=True)

        plan = plan_migration(
            guild.members,
            recruit=recruit, club=club, captain_role=captain_role, squad_role=squad_role,
            captain_member=captain_member, give_club_to_all=give_football_club_to_all, old_role=remove_old_role,
        )
        lines = [f"Captain: {captain_member.display_name}"]
        for member, (add, remove) in plan.items():
            bits = []
            if add:
                bits.append("+ " + ", ".join(r.name for r in add))
            if remove:
                bits.append("- " + ", ".join(r.name for r in remove))
            lines.append(f"{member.display_name}: " + "; ".join(bits))

        everyone, football = announcement_members(plan, captain_member)
        announcements = get_channel(self.bot, guild, "announcements")
        reception = get_channel(self.bot, guild, "reception")
        if announce and (announcements is None or reception is None):
            lines.append("⚠ I can't find #announcements or #reception, so I can't announce. Run `/setup run` first.")
            announce = False
        if announce:
            lines.append(f"📣 {'Would post' if dry_run else 'Posted'} the relaunch announcement and a roll call of "
                         f"{len(everyone)} member(s) in #announcements.")
            if give_football_club_to_all and football:
                lines.append(f"⚽ {'Would post' if dry_run else 'Posted'} one football welcome for {len(football)} "
                             f"member(s) in #reception.")

        if not dry_run:
            failed = 0
            for member, (add, remove) in plan.items():
                try:
                    if add:
                        await member.add_roles(*add, reason="MR_Quartermaster /setup migrate")
                    if remove:
                        await member.remove_roles(*remove, reason="MR_Quartermaster /setup migrate")
                except discord.HTTPException:
                    failed += 1
            if failed:
                lines.append(f"⚠ {failed} member(s) could not be updated.")
            if announce and everyone:
                await self._announce(guild, announcements, reception, everyone, football if give_football_club_to_all else [])

        header = (f"**Preview only.** {len(plan)} member(s) would change:" if dry_run
                  else f"**Done.** Updated {len(plan)} member(s):")
        await _reply_chunks(interaction, header, lines or ["Nobody needs changes."])

    async def _announce(self, guild, announcements, reception, everyone, football) -> None:
        """The one-off relaunch posts: the announcement and roll call go to #announcements, and the one combined
        football welcome goes to #reception like every other welcome."""
        rules = get_channel(self.bot, guild, "rules")
        picker = get_channel(self.bot, guild, "pick_roles")
        embed = discord.Embed(
            title="We've got a new look",
            description=(
                f"The server is now **{guild.name}**, rebuilt from the ground up. Everyone who was here is still "
                f"here, so you're already a Recruit.\n\n"
                f"Read {rules.mention if rules else '#rules'}, then pick your roles in "
                f"{picker.mention if picker else '#pick-your-roles'}."
            ),
            colour=discord.Colour.blurple(),
        )
        await send_embed(announcements, embed, pick_gif(self.bot, guild.id, "welcome"), discord.AllowedMentions.none())
        for block in mention_blocks([m.mention for m in everyone]):
            await announcements.send(f"Roll call: {block}", allowed_mentions=discord.AllowedMentions(users=everyone))
        if football:
            names = " ".join(m.mention for m in football)
            football_embed = discord.Embed(
                title="⚽ MRFC Academy has opened its doors",
                description=f"Everyone below has joined the football club: {names}\nMatches are scheduled in the MRFC section.",
                colour=discord.Colour(0x2ECC71),
            )
            await send_embed(reception, football_embed, pick_gif(self.bot, guild.id, "football"),
                             discord.AllowedMentions.none())

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
