import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        
        # 檢查中央大腦狀態
        self.has_ai = hasattr(bot, 'ask_brain') and bot.ai_model is not None
        self.ai_status = "🟢 線上 (Gemini 2.0 Central)" if self.has_ai else "🔴 離線 (API Error)"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    async def ask_kobe(self, prompt):
        if not self.has_ai: return "軟蛋！連 AI 都懶得理你 🥚"
        sys_prompt = "你是 Kobe Bryant。請用毒舌、嚴格但勵志的語氣介紹你的功能。繁體中文(台灣)。"
        # 呼叫主程式的 AI
        return await self.bot.ask_brain(prompt, system_instruction=sys_prompt) or "Mamba Out."

    # --- 按鈕 1: 首頁 ---
    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        # 首頁不需要 AI，直接更新即可
        latency = round(self.bot.latency * 1000) if self.bot.latency else 0
        embed = discord.Embed(
            title="🐍 Kobe Bot · 曼巴訓練營總部",
            description=(
                "歡迎來到曼巴精神訓練營。\n"
                "我會全天候監控你的行為，直到你學會什麼是曼巴精神。\n\n"
                f"**🧠 AI 大腦**：`{self.ai_status}`\n"
                f"**⚡ 系統延遲**：`{latency}ms`\n"
                f"**🌍 監控伺服器**：{len(self.bot.guilds)} 座"
            ),
            color=0xf1c40f
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name} | Mamba Never Quits")
        
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 2: 被動監控 (AI 生成 -> 需 Defer) ---
    @discord.ui.button(label="全自動監控", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        # 🔥 關鍵修復：先告訴 Discord "請稍等"，防止 404 超時
        await interaction.response.defer() 
        
        try:
            ai_desc = await self.ask_kobe("介紹你如何監控球員：Spotify品味、已讀不回、負能量、錯字糾察、半夜不睡覺。")
            
            embed = discord.Embed(
                title="🛡️ 曼巴全方位監控 (無須指令)",
                description=ai_desc,
                color=0xe74c3c
            )
            embed.add_field(name="🎵 DJ Mamba", value="聽軟歌？直接開罵。", inline=False)
            embed.add_field(name="💤 已讀不回", value="Tag 10分鐘不回？板凳伺候。", inline=False)
            embed.add_field(name="📝 細節糾察", value="錯字/邏輯不通？嚴厲糾正。", inline=False)
            
            # 因為已經 defer 過了，要用 edit_original_response 來更新訊息
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception as e:
            print(f"Help Error: {e}")

    # --- 按鈕 3: 主動指令 ---
    @discord.ui.button(label="主動指令", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        # 靜態內容，不需要 defer，直接 edit
        embed = discord.Embed(
            title="⚡ 戰術板 (Active Commands)",
            description="主動查詢你的狀態與表現。",
            color=0x2ecc71
        )
        embed.add_field(name="`!status` / `!st`", value="📊 **曼巴監控中心** (查狀態)", inline=False)
        embed.add_field(name="`!rank` / `!r`", value="🏆 **遊戲時長排行榜**", inline=False)
        embed.add_field(name="`!summary`", value="📋 **戰術檢討會議** (AI 總結聊天)", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "面板"])
    async def help_cmd(self, ctx):
        view = HelpView(self.bot, ctx)
        
        # 🔥 修復：直接在這裡生成首頁 Embed，而不是去呼叫按鈕函式
        latency = round(self.bot.latency * 1000) if self.bot.latency else 0
        embed = discord.Embed(
            title="🐍 Kobe Bot · 曼巴訓練營總部",
            description=(
                "歡迎來到曼巴精神訓練營。\n"
                f"**🧠 AI 大腦**：`{view.ai_status}`\n"
                f"**⚡ 系統延遲**：`{latency}ms`\n"
                "請點擊下方按鈕查看詳細功能。"
            ),
            color=0xf1c40f
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {ctx.author.display_name}")

        view.message = await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))
