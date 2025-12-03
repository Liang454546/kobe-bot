import discord
from discord.ext import commands
from discord.ui import View, Button
import os

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        
        # 檢查 AI 狀態
        if os.getenv("GEMINI_API_KEY"):
            self.ai_status = "🟢 線上 (Gemini 2.0)"
        else:
            self.ai_status = "🔴 離線 (使用備用語錄)"

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    # --- 分頁 1: 首頁 ---
    @discord.ui.button(label="控制台首頁", style=discord.ButtonStyle.primary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🏀 Kobe Bot 全知全能系統",
            description=(
                "歡迎來到曼巴精神訓練營。\n"
                "我不是來這裡交朋友的，我是來督促你變強的。\n\n"
                f"**🤖 AI 大腦狀態**：{self.ai_status}\n"
                f"**⏱️ 系統延遲**：`{round(self.bot.latency * 1000)}ms`\n"
                "點擊下方按鈕查看詳細功能。"
            ),
            color=0xf1c40f # 金色
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name}")
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 分頁 2: 被動技能 (Auto) ---
    @discord.ui.button(label="被動技能 (自動觸發)", style=discord.ButtonStyle.danger, emoji="👁️")
    async def passive_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="👁️ 曼巴全方位監控 (無需指令)",
            description="你的一舉一動，我都在看。",
            color=0xe74c3c # 紅色
        )
        
        embed.add_field(
            name="📸 曼巴之眼 (Mamba Vision)",
            value="傳圖片給我，我會審判你。\n• **垃圾食物/遊戲/廢圖** ⮕ 罵你墮落。\n• **健身/書本/程式碼** ⮕ 稱讚你。",
            inline=False
        )
        embed.add_field(
            name="🧠 智能大腦 (Smart Brain)",
            value=(
                "• **說謊偵測**：嘴上說「讀書」但狀態顯示「玩遊戲」⮕ 拆穿並重罰。\n"
                "• **拖延偵測**：一直說「等下、再看」⮕ 累積懶惰指數。\n"
                "• **情緒感應**：說「好累、想哭」⮕ AI 給你毒舌雞湯。\n"
                "• **藏頭詩**：說「好累」試試看。"
            ),
            inline=False
        )
        embed.add_field(
            name="📅 行程與語音 (Schedule & Voice)",
            value=(
                "• **4 AM 警察**：凌晨 4 點還在玩遊戲？死定。\n"
                "• **每日挑戰**：每天早上 6 點發布新任務。\n"
                "• **語音結算**：進語音太短(喝水?)或太長(紮實)，離開時會評分。\n"
                "• **午夜總結**：每晚 23:59 公布「今日廢物王」。"
            ),
            inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 分頁 3: 主動指令 (Active) ---
    @discord.ui.button(label="主動指令 (目標/榮譽)", style=discord.ButtonStyle.success, emoji="⚡")
    async def active_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="⚡ 自我管理指令",
            description="主動出擊，證明你的決心。",
            color=0x2ecc71 # 綠色
        )
        
        embed.add_field(
            name="📝 目標管理 (Goal System)",
            value=(
                "`!goal <內容>` - 立下誓言 (如：背20個單字)。\n"
                "`!done` - 完成目標 (獲得榮譽 +20)。\n"
                "`!giveup` - 放棄目標 (榮譽 -20，被鄙視)。"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🧘 專注與簽到",
            value=(
                "`!focus <分鐘>` - 開啟專注模式 (偷玩遊戲 = 重罰)。\n"
                "`!checkin` (或 `!ci`) - 每日簽到，累積連勝。"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 榮譽系統",
            value=(
                "`!honor [@人]` - 查看榮譽分數與階級。\n"
                "`!rank` - 查看遊戲時長排行榜。\n"
                "`!leaderboard` - 查看榮譽排行榜。\n"
                "`!respect @人` - 致敬 (+10)。\n"
                "`!blame @人` - 譴責 (-10)。"
            ),
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 支援 !h 縮寫
    @commands.command(name="help", aliases=["h"])
    async def help(self, ctx):
        view = HelpView(self.bot, ctx)
        
        # 預設顯示首頁
        embed = discord.Embed(
            title="🏀 Kobe Bot 全知全能系統",
            description=(
                "歡迎使用曼巴精神訓練營。\n"
                "我不是來這裡交朋友的，我是來督促你變強的。\n\n"
                f"**🤖 AI 大腦狀態**：{view.ai_status}\n"
                f"**⏱️ 系統延遲**：`{round(self.bot.latency * 1000)}ms`\n"
                "點擊下方按鈕查看詳細功能。"
            ),
            color=0xf1c40f
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {ctx.author.display_name}")

        view.message = await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))
