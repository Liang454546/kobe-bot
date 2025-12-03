import discord
from discord.ext import commands
from discord.ui import View, Button
import os
import asyncio
import google.generativeai as genai
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HelpView(View):
    def __init__(self, bot, ctx, model=None):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.model = model  # 優先使用從 Game Cog 傳來的已初始化模型
        self.ai_status = "🔴 離線 (備用模式)"

        # 如果沒傳 model，就嘗試自己初始化（備用方案）
        if not self.model:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                try:
                    genai.configure(api_key=api_key)
                    self.model = genai.GenerativeModel(
                        "gemini-1.5-flash",
                        generation_config={"temperature": 0.9, "max_output_tokens": 100}
                    )
                    self.ai_status = "AI 線上 (Gemini 1.5 Flash)"
                    logger.info("HelpView 獨立啟動 Gemini 成功")
                except Exception as e:
                    logger.error(f"HelpView AI 初始化失敗: {e}")
                    self.model = None
                    self.ai_status = "離線 (使用 Kobe 語錄)"
            else:
                self.ai_status = "離線 (無 API Key)"
        else:
            self.ai_status = "🟢 AI 線上 (Gemini 2.0)"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    # 真正的異步 AI 呼叫
    async def ask_kobe(self, prompt: str) -> str:
        if not self.model:
            return "軟蛋！連 AI 都懶得理你 🥚"

        full_prompt = (
            "你是 Kobe Bryant，在一個 3 人小 Discord 當毒舌教練。\n"
            "用繁體中文（台灣腔），語氣嚴厲但勵志，控制在 50 字內，多加 🏀🐍\n"
            f"任務：{prompt}"
        )

        try:
            response = await self.model.generate_content_async(full_prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Help AI 生成失敗: {e}")
            return "Mamba 不說第二次！快去訓練！🏀"

    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        latency = round(self.bot.latency * 1000) if self.bot.latency else 0

        embed = discord.Embed(
            title="Kobe Bot · 曼巴訓練營總部",
            description=(
                "歡迎來到曼巴精神訓練營。\n"
                "我不是來這裡交朋友的，我是來督促你變強的。\n\n"
                f"**🤖 AI 大腦**：`{self.ai_status}`\n"
                f"**⏱️ 延遲**：`{latency}ms`\n"
                f"**伺服器**：{len(self.bot.guilds)} 座訓練營\n"
            ),
            color=0x9b59b6
        )
        embed.set_author(name="Kobe Bryant", icon_url="https://i.imgur.com/3ZQyX0Y.png")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者：{interaction.user.display_name} | Mamba Never Quits")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="被動監控", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        ai_text = await self.ask_kobe(
            "用 Kobe 口氣解釋這個 bot 的被動功能：圖片審判、情緒偵測、凌晨4點點名、語音結算、拖延症雷達"
        )

        embed = discord.Embed(
            title="👁️ 曼巴全方位監控系統",
            description=ai_text,
            color=0xe74c3c
        )
        embed.add_field(name="功能清單", value=(
            "`傳圖` → 自動審判是否偷懶\n"
            "`說累/想睡` → 立即被罵\n"
            "`凌晨4點在線` → 全隊點名\n"
            "`打遊戲太久` → 公開處刑\n"
            "`語音掛機` → 扣榮譽分"
        ), inline=False)
        embed.set_footer(text="你逃不掉的，曼巴之眼無所不在 🐍")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="主動指令", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="⚡ 主動證明你不是軟蛋",
            description="用行動打臉拖延症！",
            color=0x2ecc71
        )
        embed.add_field(name="目標系統", value=(
            "`!goal 今天我要變強`\n"
            "`!done` → +20 榮譽分\n"
            "`!goals` → 查看全隊誓言"
        ), inline=False)
        embed.add_field(name="榮譽排行榜", value="`!rank` 查看誰最曼巴", inline=False)
        embed.add_field(name="每日任務", value="自動派發，完成有獎勵 🏆", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="關於 Kobe Bot", style=discord.ButtonStyle.gray, emoji="ℹ️")
    async def about_button(self, interaction: discord.Interaction, button: Button):
        ai_text = await self.ask_kobe("用 Kobe 的語氣介紹自己：你是誰？為什麼在這個 3 人小伺服器？")

        embed = discord.Embed(
            title="關於我 · Kobe Bryant",
            description=ai_text,
            color=0x34495e
        )
        embed.set_image(url="https://i.imgur.com/3ZQyX0Y.png")
        embed.set_footer(text="Mamba Mentality isn’t about seeking a result. It’s about the process.")

        await interaction.response.edit_message(embed=embed, view=self)

# 🔥 關鍵修正：將指令包裝在 Cog 類別中，並加上 setup 函式
class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "面板"])
    async def help_cmd(self, ctx):
        # 嘗試從 Game Cog 獲取已初始化的強大模型，省資源
        game_cog = self.bot.get_cog("Game")
        model = getattr(game_cog, "model", None) if game_cog else None

        view = HelpView(self.bot, ctx, model=model)
        message = await ctx.send("```🏀 曼巴訓練營控制面板載入中...```", view=view)
        view.message = message

# 🔥 這就是您之前缺少的「入口鑰匙」
async def setup(bot):
    await bot.add_cog(Help(bot))
