import math
import os
import random
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from db import (
    get_cooldown,
    get_user,
    increment_balances,
    log_transaction,
    set_cooldown,
    update_user,
)
from utils.logging import send_log

STARTING_CHIPS = int(os.getenv("STARTING_CHIPS", "1000"))
DAILY_COOLDOWN_HOURS = int(os.getenv("DAILY_COOLDOWN_HOURS", "20"))
WORK_COOLDOWN_MINUTES = int(os.getenv("WORK_COOLDOWN_MINUTES", "30"))
BANK_FEE_RATE = float(os.getenv("BANK_FEE_RATE", "0.02"))  # 2% 手續費


def fmt(amount: int) -> str:
    return f"{amount:,}"


class EconomyCog(commands.Cog):
    """Money-related slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------
    #  Internal helpers
    # ------------------------------
    async def _join(self, user: discord.abc.User) -> str:
        profile = await get_user(user.id)
        if profile.get("joined"):
            return (
                f"{user.mention} 你已加入曼巴大賭場，目前錢包有 {fmt(profile['wallet'])}。"
            )

        await update_user(
            user.id,
            {
                "$set": {"joined": True},
                "$inc": {"wallet": STARTING_CHIPS},
            },
        )
        await log_transaction(
            user.id,
            kind="join",
            amount=STARTING_CHIPS,
            balance_after=STARTING_CHIPS,
        )
        await send_log(
            self.bot, f"🟢 {user.mention} 新加入賭場，獲得 {fmt(STARTING_CHIPS)}。"
        )
        return (
            f"{user.mention} 歡迎加入曼巴大賭場！"
            f"發你 {fmt(STARTING_CHIPS)} 枚籌碼，祝你好手氣。"
        )

    async def _wallet(self, user: discord.abc.User) -> str:
        profile = await get_user(user.id)
        return (
            f"{user.mention} 錢包：{fmt(profile['wallet'])}｜"
            f"銀行：{fmt(profile['bank'])}"
        )

    async def _daily(self, user: discord.abc.User) -> str:
        profile = await get_user(user.id)
        if not profile.get("joined"):
            return f"{user.mention} 先加入賭場，才能領每日獎金。"

        cooldown = await get_cooldown(user.id, "daily")
        now = datetime.utcnow()
        if cooldown and cooldown > now:
            ts = int(cooldown.timestamp())
            return f"{user.mention} 再等 <t:{ts}:R> 才能再領每日獎金。"

        reward = random.randint(200, 600)
        updated = await increment_balances(user.id, wallet_delta=reward)
        next_time = now + timedelta(hours=DAILY_COOLDOWN_HOURS)
        await set_cooldown(user.id, "daily", next_time)
        await log_transaction(
            user.id, kind="daily", amount=reward, balance_after=updated["wallet"]
        )
        return (
            f"{user.mention} 每日簽到成功！拿到 {fmt(reward)}，"
            f"現在共有 {fmt(updated['wallet'])}。"
        )

    async def _work(self, user: discord.abc.User) -> str:
        profile = await get_user(user.id)
        if not profile.get("joined"):
            return f"{user.mention} 先加入賭場再來上班。"

        cooldown = await get_cooldown(user.id, "work")
        now = datetime.utcnow()
        if cooldown and cooldown > now:
            ts = int(cooldown.timestamp())
            return f"{user.mention} 休息一下，<t:{ts}:R> 後再來打工。"

        job, pay = random.choice(
            [
                ("球館清潔工", random.randint(120, 220)),
                ("曼巴精神演講者", random.randint(200, 320)),
                ("黑曼巴貼身保鑣", random.randint(250, 400)),
                ("籌碼核算員", random.randint(180, 260)),
                ("VIP 調酒師", random.randint(220, 360)),
            ]
        )
        updated = await increment_balances(user.id, wallet_delta=pay)
        next_time = now + timedelta(minutes=WORK_COOLDOWN_MINUTES)
        await set_cooldown(user.id, "work", next_time)
        await log_transaction(
            user.id, kind="work", amount=pay, balance_after=updated["wallet"]
        )
        await send_log(
            self.bot, f"⚒️ {user.mention} 當了 {job}，賺了 {fmt(pay)}。"
        )
        return (
            f"{user.mention} 你剛擔任 **{job}**，拿到 {fmt(pay)}，"
            f"現在共有 {fmt(updated['wallet'])}。"
        )

    async def _move_money(
        self,
        user: discord.abc.User,
        *,
        amount: int,
        direction: str,
    ) -> str:
        if amount <= 0:
            return "金額需為正整數。"

        profile = await get_user(user.id)
        if direction == "deposit":
            if profile["wallet"] < amount:
                return f"{user.mention} 錢包不足，只剩 {fmt(profile['wallet'])}。"
            fee = math.ceil(amount * BANK_FEE_RATE)
            transfer = max(amount - fee, 0)
            updated = await increment_balances(
                user.id, wallet_delta=-amount, bank_delta=transfer
            )
            await log_transaction(
                user.id,
                kind="deposit",
                amount=transfer,
                balance_after=updated["wallet"],
                meta={"fee": fee},
            )
            return (
                f"{user.mention} 存入 {fmt(transfer)}（扣手續費 {fmt(fee)}），"
                f"銀行：{fmt(updated['bank'])}。"
            )

        # withdraw
        if profile["bank"] < amount:
            return f"{user.mention} 銀行不足，只剩 {fmt(profile['bank'])}。"

        updated = await increment_balances(
            user.id, wallet_delta=amount, bank_delta=-amount
        )
        await log_transaction(
            user.id,
            kind="withdraw",
            amount=amount,
            balance_after=updated["wallet"],
        )
        return (
            f"{user.mention} 提領 {fmt(amount)}，"
            f"錢包：{fmt(updated['wallet'])}。"
        )

    # ------------------------------
    #  Slash commands
    # ------------------------------
    @app_commands.command(name="join", description="加入曼巴大賭場")
    async def join(self, interaction: discord.Interaction):
        message = await self._join(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="balance", description="查看錢包與銀行資訊")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            await self._wallet(interaction.user), ephemeral=True
        )

    @app_commands.command(name="daily", description="領取每日獎金")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            await self._daily(interaction.user), ephemeral=True
        )

    @app_commands.command(name="work", description="去打工賺錢")
    async def work(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            await self._work(interaction.user), ephemeral=True
        )

    @app_commands.command(name="deposit", description="把錢存進銀行")
    @app_commands.describe(amount="欲存入的金額")
    async def deposit(self, interaction: discord.Interaction, amount: int):
        await interaction.response.send_message(
            await self._move_money(interaction.user, amount=amount, direction="deposit"),
            ephemeral=True,
        )

    @app_commands.command(name="withdraw", description="從銀行提領到錢包")
    @app_commands.describe(amount="欲提領的金額")
    async def withdraw(self, interaction: discord.Interaction, amount: int):
        await interaction.response.send_message(
            await self._move_money(interaction.user, amount=amount, direction="withdraw"),
            ephemeral=True,
        )

    # ------------------------------
    # Legacy !h command
    # ------------------------------
    @commands.command(name="h")
    async def legacy_help(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🏀 曼巴大賭場",
            description="輸入 `/` 指令即可操作，或使用下方按鈕快速互動。",
            color=discord.Color.purple(),
        )
        embed.add_field(name="加入", value="`/join` 取得起始籌碼。", inline=False)
        embed.add_field(name="賺錢", value="`/work` 打工、`/daily` 領薪。", inline=False)
        embed.add_field(name="資產", value="`/balance` 查看、`/deposit` / `withdraw` 管理銀行。", inline=False)
        await ctx.send(embed=embed, view=HubView(self))


class HubView(discord.ui.View):
    """Buttons for quick actions."""

    def __init__(self, cog: EconomyCog):
        super().__init__(timeout=120)
        self.cog = cog

    async def _respond(self, interaction: discord.Interaction, message: str):
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="加入賭場", style=discord.ButtonStyle.success, emoji="🎟️")
    async def join_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._join(interaction.user))

    @discord.ui.button(label="每日簽到", style=discord.ButtonStyle.primary, emoji="🗓️")
    async def daily_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._daily(interaction.user))

    @discord.ui.button(label="我要打工", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def work_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._respond(interaction, await self.cog._work(interaction.user))

    @discord.ui.button(label="查餘額", style=discord.ButtonStyle.secondary, emoji="💰")
    async def balance_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        await self._respond(interaction, await self.cog._wallet(interaction.user))


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))

