import discord
from discord.ext import commands
from discord.ui import View, Button

# 定義按鈕互動的視圖 (View)
class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=180) # 按鈕 3 分鐘後失效
        self.bot = bot
        self.ctx = ctx
        self.current_page = "home"

    async def on_timeout(self):
        # 時間到之後，把按鈕失效 (變灰色)
        for child in self.children:
            child.disabled = True
        # 嘗試更新原本的訊息，如果訊息被刪了就忽略
        try:
            await self.message.edit(view=self)
        except:
            pass

    # --- 1. 首頁按鈕 ---
    @discord.ui.button(label="首頁", style=discord.ButtonStyle.secondary, emoji="🏠")
    async def home_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.get_home_embed(), view=self)

    # --- 2. 遊戲與經濟按鈕 ---
    @discord.ui.button(label="遊戲 & 經濟", style=discord.ButtonStyle.primary, emoji="🎮")
    async def game_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.get_game_embed(), view=self)

    # --- 3. 語音與其他按鈕 ---
    @discord.ui.button(label="語音 & 其它", style=discord.ButtonStyle.success, emoji="🔊")
    async def voice_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.get_voice_embed(), view=self)

    # --- Helper: 產生 Embed 的函式 ---
    def get_home_embed(self):
        embed = discord.Embed(
            title="🏀 Kobe Bot 互動控制台",
            description=(
                "歡迎使用 Kobe Bot！\n"
                "我是為了貫徹 **曼巴精神 (Mamba Mentality)** 而生的機器人。\n\n"
                "請點擊下方的 **按鈕** 來查看不同功能的詳細指令。"
            ),
            color=0xf1c40f # 金色
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"召喚者: {self.ctx.author.display_name}")
        return embed

    def get_game_embed(self):
        embed = discord.Embed(
            title="🎮 遊戲與經濟系統",
            description="這裡紀錄大家偷懶玩遊戲的時間，以及曼巴幣交易。",
            color=0x3498db # 藍色
        )
        # 遊戲指令
        embed.add_field(
            name="📊 排名與紀錄",
            value=(
                "`!rank` - 查詢伺服器偷懶排行榜 (遊戲時長)。\n"
                "*機器人會自動偵測遊戲並紀錄，不需要手動開始。*"
            ),
            inline=False
        )
        # 經濟指令
        embed.add_field(
            name="💰 曼巴經濟 (Mamba Economy)",
            value=(
                "`!wallet` - 查看錢包餘額 & **領取每日獎勵** (昨日玩 < 1小時)。\n"
                "`!buy` - 開啟曼巴雜貨店 (查看可購買的商品)。\n"
                "`!buy roast @人` - 花 5 幣請我罵爆他。\n"
                "`!buy pardon` - 花 20 幣消除今日遊戲紀錄。\n"
                "`!buy rename @人` - 花 50 幣強制幫他改羞恥暱稱。"
            ),
            inline=False
        )
        return embed

    def get_voice_embed(self):
        embed = discord.Embed(
            title="🔊 語音與其他功能",
            description="自動化的語音助理與彩蛋功能。",
            color=0x2ecc71 # 綠色
        )
        embed.add_field(
            name="🎧 語音小跟班",
            value=(
                "• **自動加入**：當你進入語音頻道，我會自動跟隨。\n"
                "• **自動離開**：當頻道沒人時，我會自動省電登出。\n"
                "• **叫我滾**：在文字頻道輸入 **「滾」**，我會罵回去然後斷線。"
            ),
            inline=False
        )
        embed.add_field(
            name="🤬 曼巴精神罵人",
            value=(
                "• 當我偵測到你在玩 **GTA, NBA 2K, LOL, 原神** 等遊戲時，\n"
                "• 我會隨機在公頻標記你並進行「曼巴式開導」。"
            ),
            inline=False
        )
        return embed

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx):
        # 建立 View (按鈕控制器)
        view = HelpView(self.bot, ctx)
        # 發送預設的首頁 Embed，並附帶 View (按鈕)
        view.message = await ctx.send(embed=view.get_home_embed(), view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))
