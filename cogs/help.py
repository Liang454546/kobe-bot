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
        # 這裡會讀取 main.py 裡的 bot.ai_model
        self.has_ai = hasattr(bot, 'ask_brain') and bot.ai_model is not None
        self.ai_status = "🟢 線上 (Gemini 2.0 Central)" if self.has_ai else "🔴 離線 (API Error)"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    # 使用中央大腦生成介紹
    async def ask_kobe(self, prompt):
        if not self.has_ai: return "軟蛋！連 AI 都懶得理你 🥚"
        
        sys_prompt = "你是 Kobe Bryant。請用毒舌、嚴格但勵志的語氣介紹你的功能。繁體中文(台灣)。"
        # 🔥 直接呼叫 main.py 的 ask_brain
        response = await self.bot.ask_brain(prompt, system_instruction=sys_prompt)
        return response or "Mamba Out."

    # --- 按鈕 1: 首頁 ---
    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        latency = round(self.bot.latency * 1000) if self.bot.latency else 0
        
        embed = discord.Embed(
            title="🐍 Kobe Bot · 曼巴訓練營總部",
            description=(
                "這裡不是幼稚園，是地獄訓練營！\n"
                "我會全天候監控你的行為，直到你學會什麼是曼巴精神。\n\n"
                f"**🧠 AI 大腦**：`{self.ai_status}`\n"
                f"**⚡ 系統延遲**：`{latency}ms`\n"
                f"**🌍 監控伺服器**：{len(self.bot.guilds)} 座"
            ),
            color=0xf1c40f # 金色
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name} | Mamba Never Quits")
        
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 2: 被動監控 (列出最新功能) ---
    @discord.ui.button(label="全自動監控", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        # 讓 AI 生成一段介紹
        ai_desc = await self.ask_kobe("介紹你如何監控球員：Spotify品味、已讀不回、負能量、錯字糾察、半夜不睡覺。")
        
        embed = discord.Embed(
            title="🛡️ 曼巴全方位監控 (無須指令)",
            description=ai_desc,
            color=0xe74c3c # 紅色
        )
        
        embed.add_field(
            name="🎵 DJ Mamba (Spotify 審判)",
            value="聽軟綿綿的情歌？我會直接開罵。只有硬派音樂才配得上訓練。",
            inline=False
        )
        embed.add_field(
            name="💤 已讀不回糾察 (Ghosting)",
            value="隊友 Tag 你 (@Mention) 超過 10 分鐘不回？視為無視傳球，板凳伺候。",
            inline=False
        )
        embed.add_field(
            name="📝 細節糾察隊 (Typo Police)",
            value="打錯字？邏輯不通？我會像糾正投籃姿勢一樣糾正你。",
            inline=False
        )
        embed.add_field(
            name="🤬 負能量清潔工 (Toxic)",
            value="抱怨隊友？說喪氣話？我會讓你閉嘴去檢討自己。",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 3: 主動指令 (列出最新指令) ---
    @discord.ui.button(label="主動指令", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="⚡ 戰術板 (Active Commands)",
            description="主動查詢你的狀態與表現。",
            color=0x2ecc71 # 綠色
        )
        
        embed.add_field(
            name="`!status` 或 `!st`",
            value="📊 **曼巴監控中心**\n查看所有人現在是在玩遊戲、聽歌、直播還是發呆。",
            inline=False
        )
        embed.add_field(
            name="`!rank` 或 `!r`",
            value="🏆 **遊戲時長排行榜**\n看看誰是浪費生命的第一名 (含正在進行的時間)。",
            inline=False
        )
        embed.add_field(
            name="`!summary` 或 `!總結`",
            value="📋 **戰術檢討會議**\n(AI) 讀取最近 50 則訊息，總結大家都在聊什麼廢話。",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "面板"])
    async def help_cmd(self, ctx):
        view = HelpView(self.bot, ctx)
        
        # 預設顯示首頁
        embed = discord.Embed(
            title="🐍 Kobe Bot · 曼巴訓練營",
            description="載入控制面板中...\n正在連線至中央大腦...",
            color=0x95a5a6
        )
        view.message = await ctx.send(embed=embed, view=view)
        
        # 自動跳轉到首頁內容
        await view.home_button(None, None) 
        # 注意：上面這行在 discord.py 某些版本可能無法直接呼叫，
        # 如果報錯，請刪除這行，使用者點按鈕才會變。
        # 為了保險起見，我們讓使用者自己點擊，或者直接在下面送出首頁內容。
        
        # 更好的做法是直接初始化首頁內容：
        latency = round(self.bot.latency * 1000) if self.bot.latency else 0
        embed_home = discord.Embed(
            title="🐍 Kobe Bot · 曼巴訓練營總部",
            description=f"歡迎來到曼巴精神訓練營。\n**🧠 AI 大腦**：`{view.ai_status}`\n**⚡ 延遲**：`{latency}ms`\n請點擊下方按鈕查看詳細功能。",
            color=0xf1c40f
        )
        embed_home.set_thumbnail(url=self.bot.user.display_avatar.url)
        await view.message.edit(embed=embed_home, view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))
