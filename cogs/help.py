import discord
from discord.ext import commands
from discord.ui import View, Button

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

    # --- 按鈕 1: 首頁 ---
    @discord.ui.button(label="首頁", style=discord.ButtonStyle.secondary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.get_home_embed(), view=self)

    # --- 按鈕 2: 專注與簽到 (新功能) ---
    @discord.ui.button(label="修煉 & 簽到", style=discord.ButtonStyle.primary, emoji="🔥")
    async def focus_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="🔥 專注與簽到系統", description="建立曼巴習慣，拒絕偷懶！", color=0xe67e22)
        embed.add_field(
            name="🧘 專注模式 (!focus)",
            value="`!focus <分鐘>`\n開啟一段時間的專注修煉。\n**警告**：若期間開啟遊戲，榮譽直接 **-50** 並被踢出語音！",
            inline=False
        )
        embed.add_field(
            name="📅 每日打卡 (!checkin)",
            value="`!checkin` (或 `!ci`)\n每日簽到累積連勝，連勝越多，榮譽加成越高！",
            inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕 3: 榮譽與聊天 ---
    @discord.ui.button(label="榮譽 & 社交", style=discord.ButtonStyle.success, emoji="🏆")
    async def honor_button(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="🏆 榮譽與社交系統", description="這裡靠實力說話，沒有運氣。", color=0xf1c40f)
        embed.add_field(
            name="💬 聊天監控",
            value="我會聽你們說話。\n說「累、想睡」👉 **扣分**\n說「拼了、訓練」👉 **加分**",
            inline=False
        )
        embed.add_field(
            name="🗳️ 每日評價",
            value="`!respect @人` - 致敬 (+10分)\n`!blame @人` - 譴責 (-10分)\n(每天限一次)",
            inline=False
        )
        embed.add_field(
            name="📊 查詢指令",
            value="`!honor` - 查看個人榮譽卡\n`!rank` - 查看全服榮譽榜",
            inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def get_home_embed(self):
        embed = discord.Embed(
            title="🏀 Kobe Bot 指令中心",
            description="歡迎來到曼巴修煉場。\n點擊下方按鈕查看功能。",
            color=0x2c3e50
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name}")
        return embed

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 設定 aliases=['h'] 讓 !h 也能觸發
    @commands.command(name="help", aliases=["h"])
    async def help(self, ctx):
        view = HelpView(self.bot, ctx)
        view.message = await ctx.send(embed=view.get_home_embed(), view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))
