import discord
from discord.ext import commands
import random

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # 機器人被叫「滾」時的回嗆清單
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走！🖕😤",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！🏀👎",
            "這就是你的態度？難怪你還在打低端局！🤡💀",
            "滾就滾！但我走了你的勝率也不會變高！🗑️🔥",
            "我走不是因為我怕，是因為我不屑！😤👋"
        ]

        # 機器人不在語音時的嘲諷清單
        self.not_in_voice_roasts = [
            "我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？去看醫生吧！🏥💊",
            "眼睛不需要可以捐給有需要的人！👀 我哪裡在語音裡了？",
            "你是在跟鬼說話嗎？👻 這裡只有文字頻道，清醒點！",
            "你的曼巴精神是用來幻想的嗎？🏀 我人都不在，你叫誰滾？"
        ]

    # 監聽：語音狀態改變 (自動跟隨 + 進場廣播)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        # 情況 A: 有人加入語音頻道 (且不是在頻道間移動)
        if after.channel is not None and before.channel != after.channel:
            
            # 1. 機器人自動跟隨 (如果還沒進去)
            voice_client = member.guild.voice_client
            if voice_client is None:
                try:
                    await after.channel.connect()
                except: pass
            
            # 2. 🔥 新增功能：進場 TTS 廣播 "What can I say?"
            # 尋找適合的文字頻道發送廣播
            target_names = ["chat", "general", "聊天", "公頻", "主頻道"]
            text_channel = discord.utils.find(lambda c: any(t in c.name.lower() for t in target_names) and c.permissions_for(member.guild.me).send_messages, member.guild.text_channels)
            
            # 如果找不到特定頻道，就找第一個能講話的
            if not text_channel:
                text_channel = discord.utils.find(lambda c: c.permissions_for(member.guild.me).send_messages, member.guild.text_channels)

            if text_channel:
                # 設定廣播內容
                # tts=True 會讓電腦把這段話唸出來
                msg = f"Man, what can I say? {member.display_name} 加入了！Mamba out."
                await text_channel.send(msg, tts=True)

        # 情況 B: 自動離開 (頻道沒人)
        if before.channel is not None:
            voice_client = member.guild.voice_client
            if voice_client and voice_client.channel == before.channel:
                # 如果頻道只剩機器人 1 人，就退出
                if len(before.channel.members) == 1:
                    await voice_client.disconnect()

    # 監聽：文字訊息 (關鍵字「滾」)
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        if "滾" in message.content:
            if message.guild.voice_client:
                # 在語音內：罵完後退出
                roast = random.choice(self.aggressive_leave_msgs)
                await message.channel.send(roast)
                await message.guild.voice_client.disconnect()
            else:
                # 不在語音內：嘲諷眼殘
                roast = random.choice(self.not_in_voice_roasts)
                await message.channel.send(roast)

async def setup(bot):
    await bot.add_cog(Voice(bot))
