import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime
import random  # 引入隨機模組，用來隨機罵人

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} # 記憶體中暫存： {user_id: start_time}
        self.db_name = "game_stats.db"
        
        # 這裡設定勸阻的語錄，你可以自己新增更多
        self.alert_messages = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？還不快去努力！🏀",
            "{member} 還有時間玩 **{game}**？凌晨四點的太陽看過了嗎？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！直接驅逐出場去辦正事！",
            "這時候玩 **{game}**？你的競爭對手正在訓練呢！💪"
        ]

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
        
        # 檢查新狀態是否有在玩遊戲
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

        # --- 邏輯 1: 開始玩遊戲 (新增勸阻功能) ---
        if new_game and not old_game:
            self.active_sessions[user_id] = {
                "game": new_game,
                "start": time.time()
            }
            
            # 找出要發送訊息的頻道
            # 優先傳送到系統頻道 (System Channel)，如果沒有就找第一個機器人能講話的文字頻道
            channel = after.guild.system_channel
            if not channel:
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c
                        break
            
            # 發送隨機勸阻訊息
            if channel:
                msg = random.choice(self.alert_messages).format(
                    member=after.mention, 
                    game=new_game
                )
                await channel.send(msg)

        # --- 邏輯 2: 停止玩遊戲 (結算時間) ---
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
                await ctx.send("目前沒有任何遊戲紀錄，大家都非常認真！(或是機器人壞了)")
                return

            # 使用 Embed 讓排名變漂亮
            embed = discord.Embed(
                title="🏆 偷懶排行榜 (遊戲總時長)",
                description="以下是伺服器裡最常打遊戲的人：",
                color=0xffd700 # 金色
            )

            rank_text = ""
            for index, row in enumerate(rows):
                u_id, seconds = row
                member = ctx.guild.get_member(u_id)
                name = member.display_name if member else "未知成員"
                
                # 計算小時與分鐘
                hours = seconds // 3600
                mins = (seconds % 3600) // 60
                
                # 前三名加獎盃
                medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][index]
                rank_text += f"{medal} **{name}** : {hours} 小時 {mins} 分鐘\n"
            
            embed.add_field(name="排名名單", value=rank_text, inline=False)
            embed.set_footer(text="統計數據來自機器人資料庫")
            
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Game(bot))
