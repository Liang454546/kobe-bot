import discord
from discord.ext import commands
from discord.ui import View, Button

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        # 檢查主程式有沒有 AI
        self.has_ai = hasattr(bot, 'ai_model') and bot.ai_model is not None
        self.ai_status = "🟢 線上 (Gemini 2.0)" if self.has_ai else "🔴 離線"

    async def on_timeout(self):
        for child in self.children: child.disabled = True
        try: await self.message.edit(view=self)
        except: pass

    async def ask_kobe(self, prompt):
        if not self.has_ai: return "軟蛋！連 AI 都懶得理你 🥚"
        sys_prompt = "你是 Kobe Bryant。解釋你的功能，語氣毒舌但勵志。繁體中文。"
        # 🔥 使用中央大腦
        return await self.bot.ask_brain(prompt, system_instruction=sys_prompt) or "Mamba Out."

    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="Kobe Bot · 曼巴訓練營總部",
            description=f"歡迎來到曼巴精神訓練營。\n**AI 大腦**：`{self.ai_status}`\n**延遲**：`{round(self.bot.latency * 1000)}ms`",
            color=0x9b59b6
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="被動監控", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        desc = await self.ask_kobe("介紹被動監控功能：圖片審判、情緒偵測、4AM點名、遊戲超時警告。")
        embed = discord.Embed(title="曼巴全方位監控系統", description=desc, color=0xe74c3c)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="主動指令", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="主動證明你不是軟蛋", description="`!rank` 查排名\n`!status` 查狀態", color=0x2ecc71)
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "面板"])
    async def help_cmd(self, ctx):
        view = HelpView(self.bot, ctx)
        message = await ctx.send("```🏀 曼巴訓練營控制面板載入中...```", view=view)
        view.message = message

async def setup(bot):
    await bot.add_cog(Help(bot))
