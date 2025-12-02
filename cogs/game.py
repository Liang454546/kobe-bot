import discord
from discord.ext import commands, tasks
import aiosqlite
import time
from datetime import datetime

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} # 記憶體中暫存： {user_id: start_time}
        self.db_name = "game_stats.db"

    async def cog_load(self):
        # 機器人啟動時，建立資料庫表格
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER,
                    game_name TEXT,
                    seconds INTEGER,
                    last_played DATE
                )
            ''')
            await db.commit()

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot:
            return

        user_id = after.id
        
        # 檢查新狀態是否有在玩遊戲 (ActivityType.playing)
        new_game = None
        for activity in after.activities:
            if activity.type == discord.ActivityType.playing:
                new_game = activity.name
                break
        
        # 檢查舊狀態
        old_game = None
        for activity in before.activities:
            if activity.type == discord.ActivityType.playing:
                old_game = activity.name
                break

        # 邏輯 1: 開始玩遊戲
        if new_game and not old_game:
            self.active_sessions[user_id] = {
                "game": new_game,
                "start": time.time()
            }
            # 可以在這裡加 print 或發訊息 (勸阻功能可放這)
            # await self.send_alert(after, new_game) 

        # 邏輯 2: 停止玩遊戲 (結算時間)
        elif old_game and not new_game:
            if user_id in self.active_sessions:
                session = self.active_sessions.pop(user_id)
                # 確保是同一個遊戲
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    print(f"{after.name} 玩了 {old_game} 共 {duration} 秒")

    async def save_to_db(self, user_id, game_name, seconds):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            # 這裡做簡單的插入，未來可以優化為更新累加
            await db.execute(
                "INSERT INTO playtime (user_id, game_name, seconds, last_played) VALUES (?, ?, ?, ?)",
                (user_id, game_name, seconds, today)
            )
            await db.commit()

    # 指令：查詢排名 (!rank)
    @commands.command()
    async def rank(self, ctx):
        async with aiosqlite.connect(self.db_name) as db:
            # 查詢總時長前 5 名
            cursor = await db.execute('''
                SELECT user_id, SUM(seconds) as total_time 
                FROM playtime 
                GROUP BY user_id 
                ORDER BY total_time DESC 
                LIMIT 5
            ''')
            rows = await cursor.fetchall()
            
            if not rows:
                await ctx.send("目前沒有任何遊戲紀錄！")
                return

            msg = "**🎮 遊戲時長排行榜 (總計)**\n"
            for index, row in enumerate(rows):
                u_id, seconds = row
                member = ctx.guild.get_member(u_id)
                name = member.name if member else "未知成員"
                
                hours = seconds // 3600
                mins = (seconds % 3600) // 60
                msg += f"{index+1}. **{name}**: {hours}小時 {mins}分鐘\n"
            
            await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(Game(bot))
