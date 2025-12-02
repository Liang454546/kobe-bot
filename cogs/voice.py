import discord
from discord.ext import commands

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 監聽：語音狀態改變 (加入/離開/移動)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 忽略機器人自己的變動
        if member.bot:
            return

        # 情況 A: 有人加入語音頻道 (且機器人不在裡面)
        if after.channel is not None and before.channel != after.channel:
            voice_client = member.guild.voice_client
            # 如果機器人還沒連線，就加入該頻道
            if voice_client is None:
                await after.channel.connect()
                print(f"跟隨 {member.name} 加入了 {after.channel.name}")

        # 情況 B: 有人離開語音頻道
        if before.channel is not None:
            voice_client = member.guild.voice_client
            # 如果機器人在該頻道內
            if voice_client and voice_client.channel == before.channel:
                # 檢查頻道內是否只剩下機器人 (成員數 == 1)
                if len(before.channel.members) == 1:
                    await voice_client.disconnect()
                    print(f"頻道 {before.channel.name} 沒人了，機器人退出。")

    # 監聽：文字訊息
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # 偵測關鍵字「滾」
        if "滾" in message.content:
            if message.guild.voice_client:
                await message.channel.send("好ㄉ... 😢")
                await message.guild.voice_client.disconnect()
            else:
                await message.channel.send("我根本不在語音裡面啊！")

async def setup(bot):
    await bot.add_cog(Voice(bot))
