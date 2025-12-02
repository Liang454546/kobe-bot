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
        
        # --- 1. 針對特定遊戲的罵人清單 (關鍵字 : 罵人內容) ---
        # 只要遊戲名稱包含左邊的關鍵字 (不分大小寫)，就會觸發右邊的這句話
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，這裡是現實世界！快去努力工作！",
            "grand theft auto": "還在 Grand Theft Auto？除了偷車你還會什麼？去偷點時間來唸書吧！",
            "nba": "玩 NBA 2K？🏀 你手指動得比腳還快有什麼用？曼巴精神是去球場流汗，不是在螢幕前流口水！",
            "2k": "玩 2K 建球員？不如去建設你自己的人生！別再捏臉了！",
            "league of legends": "又在打 LOL？💀 你的心態炸裂了嗎？還是想讓隊友心態炸裂？關掉它！",
            "valorant": "特戰英豪？槍法再準，考試/工作射不中目標有什麼用？",
            "原神": "啟動？😱 給我把書桌前的燈啟動！別再抽卡了，你的人生抽不到保底！"
        }

        # --- 2. 通用的隨機罵人清單 (如果沒對應到上面，就用這個) ---
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？还不快去努力！🏀",
            "{member} 還有時間玩 **{game}**？凌晨四點的太陽看過了嗎？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！直接驅逐出場去辦正事！",
            "這時候玩 **{game}**？你的競爭對手正在訓練呢！💪"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE
                )
            ''')
            await db.commit()

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        # 抓取遊戲名稱
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        # 情況 1: 開始玩遊戲 (發送勸阻)
        if new_game and not old_game:
            self.active_sessions[after.id] = {"game": new_game, "start": time.time()}
            
            # 尋找可以發話的頻道
            channel = after.guild.system_channel
            if not channel:
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c
                        break
            
            if channel:
                # --- 這裡進行「精準打擊」判斷 ---
                game_name_lower = new_game.lower() # 轉成小寫方便比對
                roast_msg = None

                # 檢查有沒有符合的關鍵字
                for keyword, msg in self.targeted_roasts.items():
                    if keyword in game_name_lower:
                        # 找到了！設定專屬罵人語
                        # 這裡我們加上 {member} 標記，讓它更像是在對人說話
                        roast_msg = f"{after.mention} {msg}"
                        break
                
                # 如果都沒對應到，就隨機選一句通用的
                if not roast_msg:
                    roast_msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                
                await channel.send(roast_msg)

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

    # 指令：查詢排名 (!rank)
    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
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

                embed = discord.Embed(
                    title="🏆 偷懶排行榜 (遊戲總時長)",
                    color=0xffd700
                )

                rank_text = ""
                for index, row in enumerate(rows):
                    u_id, seconds = row
                    member = ctx.guild.get_member(u_id)
                    name = member.display_name if member else f"已離線成員({u_id})"
                    hours = seconds // 3600
                    mins = (seconds % 3600) // 60
                    rank_text += f"第 {index+1} 名: **{name}** - {hours}小時 {mins}分\n"
                
                embed.add_field(name="統計名單", value=rank_text, inline=False)
                await ctx.send(embed=embed)
        except Exception as e:
            print(f"Rank Error: {e}")
            await ctx.send("❌ 發生錯誤，請稍後再試。")

async def setup(bot):
    await bot.add_cog(Game(bot))
