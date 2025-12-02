import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {}
        self.db_name = "game_stats.db"
        # 罵人語錄
        self.alert_messages = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.commit()

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        # 偵測是否有在玩遊戲 (Playing)
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        # 情況 1: 開始玩遊戲 (發送勸阻)
        if new_game and not old_game:
            self.active_sessions[after.id] = {"game": new_game, "start": time.time()}
            
            # 尋找可以發話的頻道
            channel = after.guild.system_channel
            if not channel:
                # 如果沒有系統頻道，找第一個文字頻道
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c
                        break
            
            if channel:
                msg = random.choice(self.alert_messages).format(member=after.mention, game=new_game)
                await channel.send(msg)

        # 情況 2: 停止玩遊戲
        elif old_game and not new_game:
            if after.id in self.active_sessions:
                session = self.active_sessions.pop(after.id)
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(after.id, old_game, duration)

    async def save_to_db(self, user_id, game_name, seconds):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()
            
    # 請保留 rank 指令...
    @commands.command()
    async def rank(self, ctx):
        # (這裡省略 rank 程式碼，請保留原本的即可)
        pass

async def setup(bot):
    await bot.add_cog(Game(bot))
