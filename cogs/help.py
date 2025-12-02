import discord
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx):
        embed = discord.Embed(
            title="🏀 Kobe Bot 使用手冊",
            description="你好！我是 Kobe Bot。這裡紀錄大家打遊戲的時間，也會陪大家蹲語音。",
            color=0xf1c40f 
        )
        
        # 遊戲功能
        game_desc = (
            "`!rank`\n"
            "查詢伺服器內的「遊戲時長排行榜」。\n"
            "*(我會自動記錄大家玩遊戲的時間，不用手動開始)*"
        )
        embed.add_field(name="🎮 遊戲統計 (Game)", value=game_desc, inline=False)

        # 語音功能
        voice_desc = (
            "**自動跟隨**：當你加入語音頻道，我會自動跟進去。\n"
            "**自動離開**：當頻道只剩我一個，或大家離開後，我會自動退出。\n"
            "**趕人指令**：在文字頻道輸入 **「滾」**，我就會哭著離開語音... 😢"
        )
        embed.add_field(name="🔊 語音小跟班 (Voice)", value=voice_desc, inline=False)

        embed.set_footer(text=f"查詢者：{ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))
