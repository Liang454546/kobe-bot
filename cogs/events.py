import logging
import random
import traceback
from datetime import datetime
from typing import List

import discord
from discord.ext import commands

from db import get_user, increment_balances, update_user, log_transaction
from utils.logging import send_log

LOGGER = logging.getLogger("kobe_bot")


TRASH_TALK_LINES: List[str] = [
    "You weren't with me shooting in the gym.",
    "I don't talk to role players.",
    "Even my wings don't block that shot.",
    "Job's not finished.",
    "If you're afraid to fail, then you're probably going to fail.",
]

RINGS_LINE = "Kobe: 5 💍  |  You: 0 😏"


class EventsCog(commands.Cog):
    """Global event handlers & Kobe easter eggs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------
    #  Core lifecycle & errors
    # ------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()
        info = f"{self.bot.user} 上線，已載入 {len(self.bot.cogs)} 個模組。"
        LOGGER.info(info)
        await send_log(self.bot, f"✅ {info}")

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ):
        LOGGER.error(
            "Slash command error: %s", "".join(traceback.format_exception(error))
        )
        message = "😵 指令失敗了，請稍後再試或回報管理員。"
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        LOGGER.error(
            "Prefix command error: %s", "".join(traceback.format_exception(error))
        )
        await ctx.reply("😵 指令失敗了，請稍後再試或回報管理員。", mention_author=False)

    # ------------------------------
    #  Message listener: Kobe 彩蛋 + XP
    # ------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content
        lowered = content.lower()

        # 指令開頭就交給指令系統處理（仍然會在最後呼叫 process_commands）
        is_prefix_cmd = content.startswith("!")

        # 關鍵字彩蛋
        triggers = [
            (["傳球", "pass"], [
                "🚫 Kobe 不傳球的，自己投！",
                "Get the rebound!",
            ]),
            (["81"], ["🏀 那晚之後，Jalen Rose 再也不敢看我。"]),
            (["軟", "soft"], ["😤 Soft. You're soft."]),
            (["詹姆斯", "lebron", "喬丹", "mj"], ["🐐 他們很強，但我才是 GOAT。"]),
            (["絕殺", "clutch"], ["🔥 Mamba Mentality."]),
            (["鐵", "打鐵"], ["🧱 那不是打鐵，那是透過籃框傳球給隊友。"]),
        ]
        for keys, replies in triggers:
            if any(k.lower() in lowered for k in keys):
                # 避免洗版，只回一則
                await message.channel.send(random.choice(replies))
                break

        # 表情反應
        try:
            if any(k in lowered for k in ["籃球", "basketball"]):
                await message.add_reaction("🏀")
            if any(k in lowered for k in ["第一", "冠軍"]):
                await message.add_reaction("💍")
            if any(k in lowered for k in ["蛇", "snake"]):
                await message.add_reaction("🐍")
        except discord.HTTPException:
            pass

        # 其餘邏輯只對一般聊天訊息生效（避免每個指令都加 XP / 稅）
        user_profile = None
        if not is_prefix_cmd and content:
            # XP / 等級系統（簡易版）
            try:
                user_profile = await get_user(message.author.id)
                xp_gain = random.randint(5, 10)
                old_xp = user_profile.get("xp", 0)
                old_level = user_profile.get("level", 1)
                new_xp = old_xp + xp_gain
                # 簡單等級公式：每 200 XP 升 1 級
                new_level = max(1, 1 + new_xp // 200)
                if new_level > old_level:
                    await update_user(
                        message.author.id,
                        {"$set": {"xp": new_xp, "level": new_level}},
                    )
                    base = f"{message.author.mention} 升級到 Lv.{new_level}！"
                    extra = ""
                    if new_level in (8, 24):
                        extra = (
                            " 💜💛 曼巴認同你的努力——背號加持，"
                            "記得把每一次出手當成最後一次。"
                        )
                    await message.channel.send(base + extra)
                    # 既然已拿到最新資料，後面就重查
                    user_profile = None
                else:
                    await update_user(
                        message.author.id,
                        {"$set": {"xp": new_xp}},
                    )
            except Exception as exc:  # XP 失敗不應影響正常聊天
                LOGGER.debug("XP update failed: %s", exc)

        # 曼巴稅：極低機率觸發（只對聊天，不對指令）
        try:
            if not is_prefix_cmd and content and random.random() < 0.01:
                if user_profile is None:
                    user_profile = await get_user(message.author.id)
                wallet = user_profile.get("wallet", 0)
                if wallet >= 24:
                    await increment_balances(message.author.id, wallet_delta=-24)
                    await log_transaction(
                        message.author.id,
                        kind="mamba_tax",
                        amount=-24,
                        balance_after=wallet - 24,
                    )
                    await message.channel.send(
                        f"🐍 **曼巴稅：{message.author.mention}** "
                        "Kobe 覺得你剛剛那句話不夠專注，沒收 24 枚籌碼。"
                    )
                else:
                    await message.channel.send(
                        f"🐍 曼巴本來想跟你收稅，但你身上也沒幾枚籌碼…先放你一馬。"
                    )
        except Exception as exc:
            LOGGER.debug("Mamba tax failed: %s", exc)

        # 讓其他指令正常運作
        await self.bot.process_commands(message)

    # ------------------------------
    #  Kobe 垃圾話 & 彩蛋指令
    # ------------------------------
    @commands.command(name="trash")
    async def trash(self, ctx: commands.Context):
        """隱藏指令：Kobe 垃圾話"""
        await ctx.reply(random.choice(TRASH_TALK_LINES), mention_author=False)

    @commands.command(name="rings")
    async def rings(self, ctx: commands.Context):
        """隱藏指令：Kobe 冠軍數"""
        await ctx.reply(RINGS_LINE, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))

