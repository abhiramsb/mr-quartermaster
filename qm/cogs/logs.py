"""#bot-logs: joins, leaves, role changes and bans. Needs no message-content access."""
from __future__ import annotations

import discord
from discord.ext import commands

from ..util import send_log


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        created = discord.utils.format_dt(member.created_at, "R")
        await send_log(self.bot, member.guild, f"📥 {member.mention} joined. Account created {created}.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await send_log(self.bot, member.guild, f"📤 **{member}** left.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not (added or removed):
            return
        parts = []
        if added:
            parts.append("added " + ", ".join(f"**{r.name}**" for r in added))
        if removed:
            parts.append("removed " + ", ".join(f"**{r.name}**" for r in removed))
        await send_log(self.bot, after.guild, f"🏷 {after.mention}: " + "; ".join(parts))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await send_log(self.bot, guild, f"🔨 **{user}** was banned.")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await send_log(self.bot, guild, f"♻ **{user}** was unbanned.")


async def setup(bot):
    await bot.add_cog(Logs(bot))
