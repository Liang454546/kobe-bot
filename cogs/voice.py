import discord
from discord.ext import commands
import random

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 🔥 超兇狠的回嗆語錄 (加入大量符號與嘲諷)
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走，反正這裡全是魯蛇的味道！🖕😤",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！像你這種心態永遠打不了NBA！🏀👎",
            "這就是你的態度？難怪你還在打低端局！我看不起你！🤡💀",
            "滾就滾！但我走了你的勝率也不會變高，因為爛的是你的人！🗑️🔥",
            "我走不是因為我怕，是因為我不屑跟不想贏的人呼吸同樣的空氣！😤👋",
            "你在教我做事？你連自己的人生都控制不了還想控制我？可笑！💢😂",
            "好啊我滾！但在我滾之前記住：凌晨四點的太陽你永遠看不到了，因為你在睡大覺！💤🚫",
            "廢物心態！遇到強者就叫人滾？這就是為什麼你永遠是替補！🪑📉"
        ]

    # 監聽：語音狀態改變 (自動跟隨/自動離開)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        # 自動跟隨 (有人進語音)
        if after.channel is not None and before.channel != after.channel:
            voice_client = member.guild.voice_client
            if voice_client is None:
                try:
                    await after.channel.connect()
                except:
                    pass # 處理連線權限問題

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
                # 如果不在語音裡，也要嗆一下
                await message.channel.send("我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？去看醫生吧！🏥💊")

async def setup(bot):
    await bot.add_cog(Voice(bot))
