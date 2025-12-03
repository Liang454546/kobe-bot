import discord
from discord.ext import commands
from discord.ui import View, Button
import os
import asyncio  # 新增：AI async
import google.generativeai as genai  # 新增：借 AI
import logging  # 新增：log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.message = None  # 新增：預設 message
        
        # 檢查 AI 狀態（修：準確版）
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro-vision")
                self.ai_status = "🟢 線上 (Gemini Pro Vision)"
            except Exception as e:
                logger.error(f"AI 檢查失敗: {e}")
                self.ai_status = "🔴 離線 (備用模式)"
                self.model = None
        else:
            self.ai_status = "🔴 離線 (使用 Kobe 語錄)"
            self.model = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:  # 修：檢查 message
            try:
                await self.message.edit(view=self)
            except:
                pass

    # AI Kobe 生成（借 Game 邏輯，簡化）
    async def ask_kobe(self, prompt):
        if not self.model: return None
        try:
            sys_prompt = "你是 Kobe Bryant，在 3 人小 Discord 伺服器解釋 bot 功能。語氣毒舌勵志，繁體中文(台灣)，簡短(50字內)，多 emoji (🏀🐍)。"
            contents = [sys_prompt, prompt]
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI Help 生成失敗: {e}")
            return None

    # --- 按鈕 1: 首頁（加今日 stats 預覽） ---
    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        # 模擬 stats（整合 Game/DB，假設有 get_stats 函式；否則備用）
        try:
            latency = round(self.bot.latency * 1000)
        except:
            latency = "N/A"
        
        embed = discord.Embed(
            title="🏀 Kobe Bot 全知全能系統",
            description=(
                "歡迎來到曼巴精神訓練營。\n"
                "我是來督促你變強的，軟蛋！🐍\n\n"
                f"**🤖 AI 大腦**：{self.ai_status}\n"
                f"**⏱️ 延遲**：`{latency}ms`\n"
                "**📊 今日廢物指數**：0/100 (還早，繼續努力？)"  # 可連 DB
            ),
            color=0xf1c40f
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name} | Mamba Out.")
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 2: 被動技能（加 AI 動態描述） ---
    @discord.ui.button(label="被動技能 (自動觸發)", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        # AI 生成描述（升級：動態）
        prompt = "解釋 Kobe Bot 被動監控功能：在 3 人小伺服器，圖片審判、情緒感應、4AM 警察、每日挑戰、語音結算。毒舌版。"
        ai_desc = await self.ask_kobe(prompt) or "你的一舉一動，我都在盯！傳圖被審、抱怨被罵、熬夜被抓。"
        
        embed = discord.Embed(
            title="👁️ 曼巴全方位監控 (無需指令)",
            description=ai_desc,
            color=0xe74c3c
        )
        
        embed.add_field(
            name="📸 曼巴之眼",
            value="垃圾圖 → 罵；努力圖 → 讚。😤",
            inline=True
        )
        embed.add_field(
            name="🧠 智能大腦",
            value="偵測拖延/情緒，午夜總結廢物王。🐍",
            inline=True
        )
        embed.add_field(
            name="📅 行程語音",
            value="4AM 點名、每日任務、語音獎懲。🏀",
            inline=True
        )
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 3: 主動指令（不變，微調） ---
    @discord.ui.button(label="主動指令 (目標/榮譽)", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="⚡ 自我管理指令",
            description="主動證明你的 Mamba 決心！",
            color=0x2ecc71
        )
        
        embed.add_field(
            name="📝 目標管理",
            value="`!goal <誓言>` - 立旗。\n`!done` +20 榮譽
