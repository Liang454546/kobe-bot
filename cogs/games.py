import os
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from db import get_user, increment_balances, log_transaction
from utils.logging import send_log

BET_LIMIT = int(os.getenv("BET_LIMIT", "20000"))


def fmt(amount: int) -> str:
    return f"{amount:,}"


class GamesCog(commands.Cog):
    """Slash commands for casino mini-games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _spend(self, user_id: int, amount: int) -> int:
        profile = await get_user(user_id)
        if profile["wallet"] < amount:
            raise ValueError(f"餘額不足，只剩 {fmt(profile['wallet'])}。")
        await increment_balances(user_id, wallet_delta=-amount)
        return profile["wallet"] - amount

    async def _reward(self, user_id: int, amount: int, kind: str) -> int:
        profile = await increment_balances(user_id, wallet_delta=amount)
        await log_transaction(
            user_id, kind=kind, amount=amount, balance_after=profile["wallet"]
        )
        return profile["wallet"]

    def _validate_amount(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("金額必須是正整數。")
        if amount > BET_LIMIT:
            raise ValueError(f"每次下注上限為 {fmt(BET_LIMIT)}。")

    async def _result(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message(message, ephemeral=True)

    # ------------------------------
    # Slash commands
    # ------------------------------
    @app_commands.command(name="bet", description="曼巴二擇一，50% 變兩倍、50% 歸零。")
    @app_commands.describe(amount="下注金額")
    async def bet(self, interaction: discord.Interaction, amount: int):
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        if random.random() < 0.5:
            new_balance = await self._reward(
                interaction.user.id, amount * 2, kind="bet_win"
            )
            message = (
                f"{interaction.user.mention} 🎉 你贏了！拿回 {fmt(amount * 2)}，"
                f"現在共有 {fmt(new_balance)}。"
            )
            await send_log(self.bot, f"🥳 {interaction.user} 贏了 bet {fmt(amount * 2)}")
        else:
            await log_transaction(
                interaction.user.id,
                kind="bet_lose",
                amount=-amount,
            )
            message = (
                f"{interaction.user.mention} 💀 你全輸了，"
                f"剩下 {fmt((await get_user(interaction.user.id))['wallet'])}。"
            )
        await self._result(interaction, message)

    @app_commands.command(name="coinflip", description="猜硬幣，贏取 1.8 倍。")
    @app_commands.describe(choice="正面或反面", amount="下注金額")
    async def coinflip(
        self,
        interaction: discord.Interaction,
        choice: Literal["正面", "反面", "heads", "tails"],
        amount: int,
    ):
        normalized = "heads" if choice in ("正面", "heads") else "tails"
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        result = random.choice(["heads", "tails"])
        if result == normalized:
            profit = int(amount * 1.8)
            new_balance = await self._reward(
                interaction.user.id, profit, kind="coinflip_win"
            )
            message = (
                f"{interaction.user.mention} 👍 硬幣是 **{result}**，贏得 {fmt(profit)}！"
                f"目前 {fmt(new_balance)}。"
            )
        else:
            await log_transaction(
                interaction.user.id,
                kind="coinflip_lose",
                amount=-amount,
            )
            message = (
                f"{interaction.user.mention} 😵 硬幣是 **{result}**，"
                f"沒中，剩下 {fmt((await get_user(interaction.user.id))['wallet'])}。"
            )
        await self._result(interaction, message)

    @app_commands.command(name="dice", description="猜骰子點數，猜中拿 5 倍。")
    @app_commands.describe(amount="下注金額", guess="你要猜的點數 (1-6)")
    async def dice(self, interaction: discord.Interaction, amount: int, guess: int):
        if guess < 1 or guess > 6:
            await self._result(interaction, "點數需在 1~6 之間。")
            return
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        roll = random.randint(1, 6)
        if roll == guess:
            payout = amount * 5
            new_balance = await self._reward(
                interaction.user.id, payout, kind="dice_win"
            )
            message = (
                f"{interaction.user.mention} 🎯 骰到 **{roll}**，你猜中啦！"
                f"贏得 {fmt(payout)}，現有 {fmt(new_balance)}。"
            )
        else:
            await log_transaction(
                interaction.user.id, kind="dice_lose", amount=-amount
            )
            message = (
                f"{interaction.user.mention} 骰到 **{roll}**，你猜 {guess}，"
                f"剩下 {fmt((await get_user(interaction.user.id))['wallet'])}。"
            )
        await self._result(interaction, message)

    @app_commands.command(name="slots", description="拉霸機")
    @app_commands.describe(amount="下注金額")
    async def slots(self, interaction: discord.Interaction, amount: int):
        reels = ["🍇", "🍋", "🍒", "⭐", "🔔", "7️⃣"]
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        result = [random.choice(reels) for _ in range(3)]
        unique = len(set(result))
        message = f"{interaction.user.mention} 🎰 結果：`{' | '.join(result)}`\n"
        if unique == 1:
            multiplier = 10 if result[0] == "7️⃣" else 5
            payout = amount * multiplier
            new_balance = await self._reward(
                interaction.user.id, payout, kind="slots_jackpot"
            )
            message += f"全線串！贏得 {fmt(payout)}，現在共有 {fmt(new_balance)}。"
        elif unique == 2:
            payout = amount * 2
            new_balance = await self._reward(
                interaction.user.id, payout, kind="slots_double"
            )
            message += f"雙連線！贏得 {fmt(payout)}，現在共有 {fmt(new_balance)}。"
        else:
            await log_transaction(
                interaction.user.id, kind="slots_lose", amount=-amount
            )
            message += (
                f"沒中，剩下 {fmt((await get_user(interaction.user.id))['wallet'])}。"
            )
        await self._result(interaction, message)

    @app_commands.command(name="roulette", description="歐洲輪盤")
    @app_commands.describe(color="紅/黑/綠", amount="下注金額")
    async def roulette(
        self,
        interaction: discord.Interaction,
        color: Literal["紅", "黑", "綠", "red", "black", "green"],
        amount: int,
    ):
        mapping = {
            "紅": "red",
            "red": "red",
            "黑": "black",
            "black": "black",
            "綠": "green",
            "green": "green",
        }
        color_key = mapping[color]
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        number = random.randint(0, 36)
        colors = {0: "green", **{n: "red" if n % 2 else "black" for n in range(1, 37)}}
        result_color = colors[number]
        color_label = {"red": "紅色", "black": "黑色", "green": "綠色"}[result_color]
        if result_color == color_key:
            multiplier = 14 if color_key == "green" else 2
            payout = amount * multiplier
            new_balance = await self._reward(
                interaction.user.id, payout, kind="roulette_win"
            )
            message = (
                f"{interaction.user.mention} 🎉 開出 {color_label} {number}！"
                f"贏得 {fmt(payout)}，現在共有 {fmt(new_balance)}。"
            )
        else:
            await log_transaction(
                interaction.user.id, kind="roulette_lose", amount=-amount
            )
            message = (
                f"{interaction.user.mention} 💔 開出 {color_label} {number}，"
                f"沒壓中，剩下 {fmt((await get_user(interaction.user.id))['wallet'])}。"
            )
        await self._result(interaction, message)

    @app_commands.command(name="horse", description="曼巴賽馬")
    @app_commands.describe(
        horse="選擇馬匹：曼巴 / 飛馬 / 猛虎",
        amount="下注金額",
    )
    async def horse(
        self,
        interaction: discord.Interaction,
        horse: Literal["曼巴", "飛馬", "猛虎"],
        amount: int,
    ):
        choices = {"曼巴": 0, "飛馬": 1, "猛虎": 2}
        emojis = ["🐍", "🐎", "🐅"]
        names = ["黑曼巴號", "飛馬號", "猛虎號"]
        try:
            self._validate_amount(amount)
            await self._spend(interaction.user.id, amount)
        except ValueError as exc:
            await self._result(interaction, str(exc))
            return

        positions = [0, 0, 0]
        finish = 10
        while max(positions) < finish:
            for i in range(3):
                positions[i] = min(finish, positions[i] + random.choice([0, 1, 1, 2]))
        winners = [idx for idx, pos in enumerate(positions) if pos == max(positions)]
        track_lines = []
        for idx, pos in enumerate(positions):
            left = "·" * pos
            right = "·" * (finish - pos)
            track_lines.append(f"{emojis[idx]} {names[idx]} │ {left}{emojis[idx]}{right}🏁")

        if choices[horse] in winners:
            payout = amount * 3
            new_balance = await self._reward(
                interaction.user.id, payout, kind="horse_win"
            )
            result_text = (
                f"🎉 你押的 {names[choices[horse]]} 奪冠，贏得 {fmt(payout)}！"
                f"剩餘 {fmt(new_balance)}。"
            )
        else:
            await log_transaction(
                interaction.user.id, kind="horse_lose", amount=-amount
            )
            winner_names = ", ".join(names[idx] for idx in winners)
            result_text = (
                f"💨 冠軍是 {winner_names}，你押的 {names[choices[horse]]} 沒跟上。"
            )

        message = f"{interaction.user.mention} 🏁 曼巴賽馬\n" + "\n".join(track_lines)
        message += f"\n{result_text}"
        await self._result(interaction, message)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesCog(bot))
