import discord
from discord.ext import commands
import random

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 兇狠的回嗆語錄
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走，你也別想贏！🖕",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！廢物再見！😡",
            "這就是你的態度？難怪你還在打低端局！👎",
            "滾就滾！反正這頻道全是失敗者的味道！😤",
            "我走不是因為我怕，是因為我不屑跟不想贏的人在一起！🏀"
        ]

    # 監聽：語音狀態改變 (自動跟隨/自動離開)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        # 自動跟隨 (有人進語音)
        if after.channel is not None and before.channel != after.channel:
            voice_client = member.guild.voice_client
            if voice_client is None:
                await after.channel.connect()

        # 自動離開 (頻道沒人)
        if before.channel is not None:
            voice_client = member.guild.voice_client
            if voice_client and voice_client.channel == before.channel:
                if len(before.channel.members) == 1:
                    await voice_client.disconnect()

    # 監聽：文字訊息 (關鍵字觸發)
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        # 偵測關鍵字「滾」
        if "滾" in message.content:
            if message.guild.voice_client:
                # 隨機選一句兇話
                roast = random.choice(self.aggressive_leave_msgs)
                await message.channel.send(roast)
                # 帥氣斷線
                await message.guild.voice_client.disconnect()
            else:
                await message.channel.send("我根本不在語音裡，你對著空氣吼什麼？傻了嗎？")

async def setup(bot):
    await bot.add_cog(Voice(bot))
