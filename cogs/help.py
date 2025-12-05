# help.py - 曼巴終極版 !h 指令（2025 最新版）
import discord
from discord.ext import commands
from discord.ui import View, Button
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=300)
        self.bot = bot
        self.ctx = ctx
        self.has_ai = hasattr(bot, 'ask_brain') and callable(getattr(bot, 'ask_brain', None))
        self.ai_status = "ONLINE (Gemini Pro)" if self.has_ai else "OFFLINE"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    @discord.ui.button(label="總部首頁", style=discord.ButtonStyle.primary, emoji="HOME")
    async def home(self, interaction: discord.Interaction, button: Button):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="KOBE BOT · 曼巴精神集中營",
            description=(
                "**你已經無路可逃了。**\n\n"
                f"**AI 大腦**：`{self.ai_status}`\n"
                f"**延遲**：`{latency}ms`　**伺服器**：`{len(self.bot.guilds)}` 座\n"
                f"**成員總數**：`{sum(g.member_count for g in self.bot.guilds):,}` 人\n\n"
                "Mamba is always watching. Always."
            ),
            color=0x8e44ad
        )
        embed.set_thumbnail(url="https://i.imgur.com/0bX9b3A.png")  # Kobe 瞪人經典圖
        embed.set_footer(text="點下方按鈕查看你逃不掉的功能")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="自動監控 · 地獄模式", style=discord.ButtonStyle.danger, emoji="EYES")
    async def passive(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="自動監控 · 24小時無死角", color=0xe74c3c)
        embed.description = (
            "我隨時在盯著你，連呼吸都逃不過。\n"
            "以下行為會被**立即處刑**：\n\n"
            "傳圖 → 自動分析並開噴\n"
            "聽悲歌 → 心理剖析 + 公開羞辱\n"
            "說「好累」「想睡」 → 自動 @ 當天最廢的人打臉你\n"
            "玩遊戲 1hr/2hr → 公開警告 + 懶惰點\n"
            "早上 8:00 還在睡 → 全頻處刑名單\n"
            "每天 9:00 意志測驗 → 60秒不回 +10懶惰點\n"
            "情緒低落 → 強制播放 Kobe 勵志影片\n"
            "情緒太嗨 → 「你們這叫興奮？我叫這幼稚」\n"
            "每晚 00:00 → 深夜戰報（今日最常說的詞）"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="主動指令 · 戰術板", style=discord.ButtonStyle.success, emoji="CLIPBOARD")
    async def active(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="主動指令列表", color=0x2ecc71)
        embed.add_field(name="狀態查詢", value=(
            "`!r` → 遊戲時長排行榜\n"
            "`!st` → 曼巴監控中心（誰在玩什麼）\n"
            "`!s` / `!songs` → 這週歌單心理分析\n"
            "`!bh @某人` → 調出他的黑歷史金句 + 總廢時"
        ), inline=False)
        embed.add_field(name="榮譽系統", value=(
            "`!goal 內容` → 立下誓言\n"
            "`!d` → 完成目標 +20 honor\n"
            "`!res @人` → 致敬 +10\n"
            "`!b @人` → 譴責 -10\n"
            "`!honor` → 查看稱號（飲水機 / 黑曼巴）"
        ), inline=False)
        embed.add_field(name="其他", value="`!h` → 你現在看到的這個", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="曼巴語錄", style=discord.ButtonStyle.grey, emoji="SNAKE")
    async def quote(self, interaction: discord.Interaction, button: Button):
        quotes = [
            "那些殺不死你的，只會讓你更強。",
            "我寧願 0.1 秒進球，也不願意 0 秒投丟。",
            "第二名只是第一個輸家。",
            "Soft. 你連蛋都不如。",
            "Mamba Out."
        ]
        embed = discord.Embed(
            title="黑曼巴語錄",
            description=f"**「{random.choice(quotes)}」**\n\n—— Kobe Bryant",
            color=0x000000
        )
        embed.set_image(url="https://i.imgur.com/J2s7iNz.png")  # Kobe 經典黑白照
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="h", aliases=["help", "幫助", "指令"])
    async def help_cmd(self, ctx):
        view = HelpView(self.bot, ctx)
        embed = discord.Embed(
            title="KOBE BOT 載入中...",
            color=0x8e44ad
        )
        message = await ctx.send(embed=embed, view=view)
        view.message = message
        # 自動跳到首頁
        await view.home(None, None)

async def setup(bot):
    await bot.add_cog(Help(bot))
