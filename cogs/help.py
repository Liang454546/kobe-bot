import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.has_ai = hasattr(bot, 'ask_brain') and bot.ai_model is not None
        self.ai_status = "🟢 線上 (Gemini 2.0)" if self.has_ai else "🔴 離線 (API Error)"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try: await self.message.edit(view=self)
        except: pass

    async def ask_kobe(self, prompt):
        if not self.has_ai: return "軟蛋！連 AI 都懶得理你 🥚"
        sys_prompt = "你是 Kobe Bryant。請用毒舌、嚴格但勵志的語氣介紹你的功能。繁體中文。"
        return await self.bot.ask_brain(prompt, system_instruction=sys_prompt) or "Mamba Out."

    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="🐍 Kobe Bot · 曼巴訓練營總部", description=f"**🧠 AI 大腦**：`{self.ai_status}`\n**伺服器**：{len(self.bot.guilds)} 座", color=0xf1c40f)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="被動監控", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        embed = discord.Embed(title="🛡️ 曼巴全方位監控", description="我隨時在看著你。", color=0xe74c3c)
        embed.add_field(name="📸 曼巴之眼", value="傳食物圖？自動算熱量。傳廢圖？直接開噴。", inline=False)
        embed.add_field(name="🎵 DJ Mamba", value="聽軟歌被罵，聽硬歌被誇。每週一公布爛歌榜。", inline=False)
        embed.add_field(name="💤 已讀不回", value="Tag 10分鐘不回？無視傳球，板凳伺候。", inline=False)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="主動指令", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="⚡ 戰術板 (Active Commands)", description="主動證明你的決心。", color=0x2ecc71)
        embed.add_field(name="🏆 榮譽指令", value="`!d` 完成目標 (+20)\n`!b @人` 譴責 (-10)\n`!res @人` 致敬 (+10)", inline=False)
        embed.add_field(name="📊 狀態查詢", value="`!st` 監控中心\n`!r` 今日戰績\n`!s` 音樂心理分析", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @commands.command(name="help", aliases=["h"])
    async def help_cmd(self, ctx):
        view = HelpView(self.bot, ctx)
        embed = discord.Embed(title="🐍 Kobe Bot", description="載入中...", color=0xf1c40f)
        view.message = await ctx.send(embed=embed, view=view)
        await view.home_button(None, None) # 預載首頁

async def setup(bot): await bot.add_cog(Help(bot))
